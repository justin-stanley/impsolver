# Security policy

## Supported versions

Only the latest released version receives fixes.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting: open the
repository's **Security** tab and choose **Report a vulnerability**. The same form is used for
responsible-use and conduct reports; say which kind it is.

You can expect an acknowledgement within 7 days and a plan within 14 days. Fixed issues are
disclosed in a GitHub security advisory and the CHANGELOG.

## Scope

impsolver runs offline on files you provide. Useful reports include:

- parsing that can execute code or read files outside the paths given;
- the HTML report (`--html`) rendering user-supplied text without escaping;
- release artifacts whose provenance does not match this repository.
