# Security policy

## Supported versions

Only the latest release receives fixes. While the version is 0.x, upgrade to the newest 0.x.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private reporting:
the repository's **Security** tab, then **Report a vulnerability**
(<https://github.com/Am1n1602/calcfinc/security/advisories/new>).

Include what you found, the smallest input that shows it, and the version. You can expect an
acknowledgement within a week. A confirmed problem is fixed in a new release and credited in the
changelog unless you prefer otherwise.

## What is in scope

calcfinc parses text it is given, so these are the surfaces that matter:

- **The formula evaluator.** Formulas are parsed with Python's `ast` and run by a small
  interpreter that allows numbers, arithmetic, names and six functions. `eval` is never used. Input
  that escapes this (attribute access, calls to other functions, a crash on deeply nested or
  enormous input, unbounded memory or time) is a vulnerability.
- **File readers.** The CSV loader, the SEC `companyfacts` JSON reader and the XBRL reader, which
  uses the standard library's XML parser (it does not fetch external entities). Anything that makes
  them execute code, read other files or exhaust resources on a reasonably sized input is in scope.
- **Storage.** All SQL uses bound parameters; an injection is in scope.
- **The one network call.** `sec_companyfacts.fetch_companyfacts` is the only code that can touch
  the network. Anything that makes other code do so is in scope.

## Out of scope

- Wrong financial results are bugs, not vulnerabilities: please open a normal issue with the data.
- Running calcfinc on untrusted XBRL with the stock parser is documented as a limit; see the manual's
  security section for the hardened-parser route.
- Denial of service by loading an enormous file you chose to load.
