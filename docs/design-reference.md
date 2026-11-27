# Design reference

Detailed formulas and defaults behind `docs/technical-design.md`. Where the two differ, the
"Changes since the original design" section of the technical design wins.

## Alignment JSON
Alignment{schema_version 1, encoding: Literal["unsigned_breaks"] (reject files without it), source,
congresses[int], kappa, min_shared, bodies{name: AlignmentBody}, half_life: float>0|None}.
half_life is omitted from the file when None (equal weight), so single-congress files are unchanged.
AlignmentBody{k, n_contested, members[AlignedMember], bloc_mean_loadings{bloc:[k]},
bloc_break_rate{bloc:float}}. Each vector has length k and norm^2<=1.
AlignedMember{id, name, party, bloc, n_votes, breaks:int|None, loadings[k], n_missed:int|None,
n_possible:int|None}. n_missed counts roll calls whose only code is 9 (not voting); n_possible
counts every roll call listing the member. Both default to None so older files load.

## Alignment fit
VOTEVIEW_PARTY {100:D,200:R,328:I}; YEA 1,2,3; NAY 4,5,6; K=5 KAPPA=50 MIN_SHARED=10 MIN_BLOC_VOTES=5,
max norm^2 0.999. Merge the two rows a party switcher gets.
1. Vote matrix: 1 yea, 0 nay, NaN otherwise.
2. Contested: the two largest blocs take opposite majorities.
3. Unsigned breaks per bloc: share=nanmean(votes[rows],0); position=where(share>.5,1,where(share<.5,0,nan));
   out[rows]=abs(votes[rows]-position)
4. Pearson: present=(~isnan(x)).astype(float); filled=nan_to_num(x); n=present@present.T;
   sx=filled@present.T; sxy=filled@filled.T; mi=sx/n; mj=sx.T/n; cov=sxy/n-mi*mj; var_i=mi(1-mi);
   var_j=mj(1-mj); corr=cov/sqrt(var_i*var_j); enough=n>=min_shared; defined=enough&var_i>0&var_j>0;
   corr=where(defined, clip(corr,-1,1), where(enough,0,nan)). A never-breaker gets 0.
5. Shrink toward the mean over defined pairs in each bloc-pair cell: w=n/(n+kappa), w=0 where NaN; diag 1.
6. Nearest correlation: symmetrize, eigh, clip negative eigenvalues to 0, rescale diag to 1 (one step).
7. Loadings = top-k eigvecs * sqrt(eigval); sign so the largest-|.| entry is positive; rescale rows to
   norm^2<=0.999.
8. Members with no history get the bloc mean loadings.
Pooling: pass the files of several congresses; roll calls are keyed (congress, rollnumber) and
members are merged by Bioguide ID within a chamber (party and bloc from the latest congress).
--half-life h gives a roll call in congress c the weight w=0.5**((latest-c)/h); default None = w=1.
With weights: n=(present*w)@present.T, sx=(filled*w)@present.T, sxy=(filled*w)@filled.T; min_shared
counts unweighted shared roll calls; shrinkage uses the weighted n; breaks, n_votes, n_missed,
n_possible are weighted sums rounded to int, and bloc_break_rate is the weighted rate. The
contested test is per roll call and unweighted.
CLI: python -m impsolver.alignment --votes --members (repeatable) --caucus 328=D --half-life --k --kappa --min-shared --out

## Copula MC
100k draws in 10k chunks, PCG64(seed). Reuse the same u across gates within a draw (scenario
`gate_correlation` < 1 mixes in a fresh draw per later gate, component by component). Marginals are
preserved. Blocs are ordered by seat order. Outputs: P(pass|reached) per gate, P(complete), yes-count
mean/p5/p50/p95, MC standard error, seed.

## Defection prior
DefectionPrior{beta=1, pseudo_votes=20, stages=["*"]}
r_i=(breaks+a*r_bloc)/(votes+a); excess=logit(r_i)-logit(r_bloc);
p_i=sigmoid(logit(p_party)+sign*beta*w*excess), sign=+1 if p_party<.5 else -1; no shift at .5.
Members with their own p or no history are untouched. p_source=defection_rate.
Propensity(breaks, votes, bloc_rate, source, weight=1). fit_beta is a logistic fit.
Calibrated: House 1.34±0.43, Senate 0.89±0.47. Fail loudly with no break counts or no member match.

## Calibrate
Crossover fixture {schema_version, case, history_congress 116, party R, bodies.house/senate.crossed[{id,name,note}], optional not_voting[{id,name,note}]}.
not_voting (2021): House 41 (116th R not Yea/Nay on roll call 17, incl. 4 Not Voting), Senate 8 (not seated 2021-02-13).
House: C001109 K000378 U000031 H001056 N000189 K000386 G000588 R000597, plus Meijer and Valadao (id null).
Senate: B001135 C001075 C001035 M001153 R000615 S001197 T000461.
Report break rate vs party, mean pairwise alignment vs 5000 random same-party sets (permutation p),
beta. min_votes 100. Expected: House 0.33 vs 0.20, p=0.014; Senate p=0.75.

## Score (calibration sweep)
`impsolver score [FIXTURES] --alignment A [--alignment A_kappa2 ...]`; default fixtures: every file in
`data/fixtures/members/`. Event = fixture; chamber scored separately. Members: party, breaks known,
n_votes >= min_votes (100), bloc has a break rate (per-member bloc rate), not on not_voting. An event
that cannot be scored (no crossers or no non-crossers, members missing) goes to skipped. Base rate b = observed crossing share (or `--base-rate`).
Marginal: p_i = sigmoid(logit b + beta*excess_i) (= priors.adjust for b < .5).
Conditional: P(y_i | y_-i) under the copula with theta = (z, w) ~ N(0, I),
q_i = Phi((Phi^-1(p_i) + sqrt(rho) z + sqrt(1-rho) a F_i.w) / (sqrt(1-rho) sqrt(1 - a^2 ||F_i||^2))).
Importance sampling from N(mode, (1.5^2) Laplace cov) given all y, dividing out member i's own
likelihood; common random numbers across the grid; min effective draws reported.
Grid defaults: beta 0..3 (11 values), rho {0, .3, .6, .9}, weight {0, .5, 1}; defaults
(beta 1, rho .6, chamber weight, kappa 50 or nearest) always added. kappa = one alignment file each.
Scores: Brier and log loss (nats), lower is better, pooled over members. Best settings and LOEO
choices skip grid points with min effective draws < 100 (unless all are). LOEO: pick the argmin
log loss on the other events, score the held-out event, alongside the defaults' held-out score.

## Viability
support_gap: bisect delta in [0,8], tol .01, CRN, 20k draws. Sort by p_complete desc, flips asc, gap asc.
Labels: viable (p>=.5), reachable (gap<=2), out of reach.

## Voteview URLs (data/voteview/)
https://voteview.com/static/data/out/votes/{H|S}{116|117|118|119}_votes.csv
https://voteview.com/static/data/out/members/{H|S}{116|117|118|119}_members.csv

## Portfolio
Portfolio{schema_version, start, deadline, house_concurrency=2, fatigue_delta=0, trial_carryover=false,
p_floor=.05, top=3, draws=5000, beam=256, exact_limit=16, calendar, candidates}
Candidate{id, scenario|p (exactly one), article, house_days>=1, senate_days>=1, release, deadline,
weight=1 (>0), after, excludes, senate_committee, committee_floor_days=2,
succession[{on_removal_of, becomes|null}], variant_of}
ChamberCalendar{weekdays [0..4], recess [(d1,d2)]}; Calendar{house, senate, trial_saturdays=true}
With `article` unset, P_i = P(any article completes) from one simulation with common random numbers
across articles; gate paths are shown for the likeliest article. With `article` set, P_i is that
article's P(complete).
Senate trials one at a time; the House has k lanes; conservative time accounting.
Objective E[removals] = sum w_i*P_i over candidates finished by their deadline.
BFS over ordered subsets with dominance pruning (same subset, value no lower, times no later). Exact up
to exact_limit, beam above it. --exhaustive turns pruning off (test oracle).
Dropped reasons: LOW_P, NO_FIT, EXCLUDED.
Fatigue: _fatigued(p0,delta,m)=p0 if p0 in {0,1} or delta==0 or m==0, else sigmoid(logit(p0)-delta*m).
P0 is the given p, or simulated once per scenario.
Sensitivity: delta in (-.2,0,.2,.5), durations x0.75/x1.25. Regret = best value minus the base order
rescheduled. FRAGILE if regret > max(.01, .05*E).
Succession: branch at the trigger's trial (removed or not); the dependent becomes its variant or is
cancelled. At most 3 triggers branch. Exhaustive up to 7 eligible candidates, otherwise re-score the
top 2000 non-branching orders. Output a decision tree.
Joint removals_dist: one shared party-swing stream across scenario candidates plus member noise.
Fatigued P is matched by a uniform shift found by bisection with CRN. Resolve succession per draw.
Fixed-p candidates are drawn independently (noted); Poisson-binomial if all are fixed.

## CLI
See the generated [CLI reference](reference/cli.md) for every command and flag.

## Roster
impsolver roster --members* --votes* --caucus PARTY=BLOC* --member-caucus ID=BLOC* ("none" = own party;
beats --caucus) --keep ID* --vacancy-gap 50 --as-of --name us-119 --out.
House seats keyed (state, district); Senate by state (2). Latest voter wins a seat; no votes = newest.
A sole holder who stopped voting more than gap before the end is a suspected vacancy unless --keep.
Exclude DC, PR and other territories. Flag caucuses set from party-level mappings.
Expected us-119: House 433 (218R/214D/1I, 2 suspected vacancies), Senate 100 (53R/45D/2I).

## Tests
thresholds, gates, paths, deterministic, flips (absences never beat flips; per-gate stance), simulate,
viability, backtest, neutrality, alignment, alignment_signs, roster, priors, portfolio, succession
(harder variant: dependent first 0.90 vs 0.78; easier variant: trigger first 1.06 vs 0.90; cancel;
depth cap), portfolio_joint (shared swings widen spread >1.5x), calibrate (real 2021 skips without data), cli.

Open questions: Kiley K000401's caucus; whether C001127 and G000594 are still seated.
