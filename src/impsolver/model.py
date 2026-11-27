"""Pydantic input models. Every model is strict and forbids unknown keys."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Chamber = Literal["house", "senate"]
Direction = Literal["pass", "fail"]
TieBreak = Literal["none", "pro", "con"]
RuleKind = Literal["majority_of_votes_cast", "fraction_of_present", "fraction_of_membership"]
Prob = Annotated[float, Field(ge=0.0, le=1.0)]
LooseDate = Annotated[dt.date, Field(strict=False)]
STAR = "*"


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


# --------------------------------------------------------------------------- rules


class ThresholdRule(Strict):
    kind: RuleKind
    p: int = 1
    q: int = 2
    present_in_denominator: bool = True
    vacancies_reduce_base: bool = True

    @model_validator(mode="after")
    def _check(self) -> ThresholdRule:
        if self.kind != "majority_of_votes_cast" and not (0 < self.p <= self.q):
            raise ValueError(f"fraction must satisfy 0 < p <= q, got {self.p}/{self.q}")
        return self


class PresidingRule(Strict):
    if_office: str = "president"
    then: str = "chief_justice"
    otherwise: str = "president_pro_tempore_or_vp"

    def officer(self, office: str) -> str:
        return self.then if office == self.if_office else self.otherwise


class Stage(Strict):
    id: str
    chamber: Chamber
    label: str
    rule: ThresholdRule
    pass_direction: Direction
    next: list[str] = []
    terminal_on_pass: bool = False
    optional: bool = False
    presiding_officer: PresidingRule | None = None


class PathSpec(Strict):
    name: str
    start: str
    requires: str | None = None


class RuleSet(Strict):
    schema_version: Literal[1]
    jurisdiction: str
    quorum: dict[Chamber, Literal["majority_of_sworn"]]
    entry: list[str]
    paths: list[PathSpec]
    stages: list[Stage]

    @model_validator(mode="after")
    def _check(self) -> RuleSet:
        ids = [s.id for s in self.stages]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate stage ids")
        known = set(ids)
        for s in self.stages:
            for n in s.next:
                if n not in known:
                    raise ValueError(f"stage {s.id} points to unknown stage {n}")
        for e in self.entry:
            if e not in known:
                raise ValueError(f"unknown entry stage {e}")
        for p in self.paths:
            if p.start not in self.entry:
                raise ValueError(f"path {p.name} starts at {p.start}, which is not an entry stage")
        return self

    def stage(self, sid: str) -> Stage:
        for s in self.stages:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def path(self, name: str) -> PathSpec:
        for p in self.paths:
            if p.name == name:
                return p
        raise KeyError(f"unknown path {name!r}; known: {[p.name for p in self.paths]}")


# --------------------------------------------------------------------- composition


class Member(Strict):
    id: str
    name: str
    party: str
    caucus: str | None = None
    state: str = "??"
    district: int | None = None
    p_pro: dict[str, Prob] = {}
    p_source: str | None = None
    ideology: float | None = None
    attendance: Literal["present", "absent"] = "present"
    notes: str | None = None

    @property
    def bloc(self) -> str:
        return self.caucus or self.party


class Body(Strict):
    seats: int = Field(gt=0)
    vacancies: int = Field(default=0, ge=0)
    members: list[Member] | None = None
    party_shorthand: dict[str, int] | None = None

    @model_validator(mode="after")
    def _expand(self) -> Body:
        if (self.members is None) == (self.party_shorthand is None):
            raise ValueError("give exactly one of members or party_shorthand")
        if self.party_shorthand is not None:
            out: list[Member] = []
            for party, n in self.party_shorthand.items():
                if n < 0:
                    raise ValueError("party_shorthand counts must be >= 0")
                out.extend(
                    Member(id=f"{party}-{i:03d}", name=f"{party} member {i}", party=party)
                    for i in range(1, n + 1)
                )
            self.members = out
            self.party_shorthand = None
        assert self.members is not None
        if len(self.members) + self.vacancies != self.seats:
            raise ValueError(
                f"members ({len(self.members)}) + vacancies ({self.vacancies}) "
                f"!= seats ({self.seats})"
            )
        ids = [m.id for m in self.members]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate member ids: {dupes}")
        return self

    @property
    def roster(self) -> list[Member]:
        assert self.members is not None
        return self.members

    @property
    def sworn(self) -> int:
        return self.seats - self.vacancies


class Composition(Strict):
    schema_version: Literal[1]
    name: str
    as_of: LooseDate
    bodies: dict[Chamber, Body]


# ------------------------------------------------------------------------ scenario


class Target(Strict):
    name: str
    office: str


class Shift(Strict):
    label: str
    bloc: str
    delta: float
    stage: str | None = None
    article: str | None = None


class DefectionPrior(Strict):
    beta: float = 1.0
    pseudo_votes: float = Field(default=20.0, gt=0)
    stages: list[str] = [STAR]


ALIGNMENT_CHAMBER_DEFAULT: dict[Chamber, float] = {"house": 1.0, "senate": 0.0}


class Scenario(Strict):
    schema_version: Literal[1]
    target: Target
    articles: list[str] = ["I"]
    rules: str
    composition: str
    party_priors: dict[str, dict[str, Prob]] = {}
    overrides: dict[str, dict[str, Prob]] = {}
    cutoffs: Annotated[tuple[float, float], Field(strict=False)] = (0.1, 0.9)
    rho: float = Field(default=0.6, ge=0.0, le=1.0)
    seed: int = 0
    shifts: list[Shift] = []
    committee_reports: bool = False
    alignment: str | None = None
    alignment_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    # Per-chamber multiplier on alignment_weight. The Senate defaults to 0: the 2021 calibration
    # found no Senate co-defection signal (permutation p = 0.75). Set it to 1 to opt in.
    alignment_chamber_weight: dict[Chamber, Annotated[float, Field(ge=0.0, le=1.0)]] = {
        "house": 1.0,
        "senate": 0.0,
    }
    # Draw one party swing per bloc shared by both chambers, instead of one per chamber.
    national_swing: bool = False
    # How an exact tie on a Senate majority vote (S1, S3) is resolved. "none" keeps the plain
    # rule (a tie defeats the motion). Whether and how a presiding officer may break such a tie in
    # an impeachment trial is not settled, so this is the user's assumption to state.
    senate_tie_break: TieBreak = "none"
    defection_prior: DefectionPrior | None = None

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        lo, hi = self.cutoffs
        if not (0.0 <= lo < hi <= 1.0):
            raise ValueError("cutoffs must satisfy 0 <= lo < hi <= 1")
        if not self.articles:
            raise ValueError("at least one article is required")
        # A partial alignment_chamber_weight keeps the default for chambers it does not name.
        self.alignment_chamber_weight = {
            **ALIGNMENT_CHAMBER_DEFAULT,
            **self.alignment_chamber_weight,
        }
        if self.defection_prior is not None and self.alignment is None:
            raise ValueError("defection_prior needs an alignment file with break counts")
        return self


# ----------------------------------------------------------------------- alignment


class AlignedMember(Strict):
    id: str
    name: str
    party: str
    bloc: str
    n_votes: int
    breaks: int | None
    loadings: list[float]


class AlignmentBody(Strict):
    k: int
    n_contested: int
    members: list[AlignedMember]
    bloc_mean_loadings: dict[str, list[float]]
    bloc_break_rate: dict[str, float]

    @model_validator(mode="after")
    def _check(self) -> AlignmentBody:
        vecs = [m.loadings for m in self.members] + list(self.bloc_mean_loadings.values())
        for v in vecs:
            if len(v) != self.k:
                raise ValueError(f"loading vector has length {len(v)}, expected k={self.k}")
            if sum(x * x for x in v) > 1.0 + 1e-9:
                raise ValueError("loading vector has norm^2 > 1")
        return self


class Alignment(Strict):
    schema_version: Literal[1]
    encoding: Literal["unsigned_breaks"]
    source: str
    congresses: list[int]
    kappa: float
    min_shared: int
    bodies: dict[str, AlignmentBody]


# ------------------------------------------------------------------------ fixtures


class FixtureVote(Strict):
    stage: str
    article: str = "I"
    yea: int
    nay: int
    present: int = 0
    not_voting: int = 0
    expected: Literal["PASS", "FAIL", "NO_QUORUM"]
    expected_short: int | None = None
    note: str | None = None


class FixtureBody(Strict):
    seats: int
    vacancies: int = 0


class Fixture(Strict):
    schema_version: Literal[1]
    case: str
    target: Target
    date: LooseDate
    path: str = "A"
    bodies: dict[Chamber, FixtureBody]
    votes: list[FixtureVote]
    expected_complete: bool = False
    expected_ends_at: str | None = None
    source: str | None = None


class CrossedMember(Strict):
    id: str | None
    name: str
    note: str | None = None


class CrossoverBody(Strict):
    crossed: list[CrossedMember]


class CrossoverFixture(Strict):
    schema_version: Literal[1]
    case: str
    history_congress: int
    party: str
    bodies: dict[Chamber, CrossoverBody]


# ----------------------------------------------------------------------- portfolio

DateRange = Annotated[tuple[LooseDate, LooseDate], Field(strict=False)]


class ChamberCalendar(Strict):
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = [0, 1, 2, 3, 4]
    recess: list[DateRange] = []


class Calendar(Strict):
    house: ChamberCalendar = ChamberCalendar()
    senate: ChamberCalendar = ChamberCalendar()
    trial_saturdays: bool = True


class Succession(Strict):
    on_removal_of: str
    becomes: str | None


class PortfolioCandidate(Strict):
    id: str
    scenario: str | None = None
    p: Prob | None = None
    article: str | None = None
    house_days: int = Field(ge=1)
    senate_days: int = Field(ge=1)
    release: LooseDate | None = None
    deadline: LooseDate | None = None
    weight: float = Field(default=1.0, gt=0.0)
    after: list[str] = []
    excludes: list[str] = []
    senate_committee: bool = False
    committee_floor_days: int = Field(default=2, ge=0)
    succession: list[Succession] = []
    variant_of: str | None = None

    @model_validator(mode="after")
    def _check(self) -> PortfolioCandidate:
        if (self.scenario is None) == (self.p is None):
            raise ValueError(f"candidate {self.id}: give exactly one of scenario or p")
        return self


class Portfolio(Strict):
    schema_version: Literal[1]
    start: LooseDate
    deadline: LooseDate
    house_concurrency: int = Field(default=2, ge=1)
    fatigue_delta: float = 0.0
    trial_carryover: bool = False
    p_floor: Prob = 0.05
    top: int = Field(default=3, ge=1)
    draws: int = Field(default=5000, ge=100)
    beam: int = Field(default=4096, ge=1)
    exact_limit: int = Field(default=10, ge=1)
    seed: int = 0
    calendar: Calendar = Calendar()
    candidates: list[PortfolioCandidate]

    @model_validator(mode="after")
    def _check(self) -> Portfolio:
        ids = [c.id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate candidate ids")
        known = set(ids)
        for c in self.candidates:
            for ref in [*c.after, *c.excludes] + ([c.variant_of] if c.variant_of else []):
                if ref not in known:
                    raise ValueError(f"candidate {c.id} references unknown candidate {ref}")
            for s in c.succession:
                if s.on_removal_of not in known or (s.becomes and s.becomes not in known):
                    raise ValueError(f"candidate {c.id} has a succession rule with unknown ids")
        if self.deadline < self.start:
            raise ValueError("deadline is before start")
        return self
