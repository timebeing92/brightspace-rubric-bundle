# Rubric Contract Family

The rubric lane has two contracts with different jobs:

- `coursecraft.rubrics/1` (`rubrics_schema.json`) is extraction evidence. It
  preserves what Brightspace exported and does not infer authoring decisions.
- `coursecraft.rubric_authoring/1` (`rubric_authoring_schema.json`) is the
  runnable authoring contract. It records explicit scoring and weight sources,
  approvals, source identity, and structured diagnostics.

Do not write inferred scores back into `coursecraft.rubrics/1`. An extraction
record may enter the authoring lane only through the strict adapter in
`scripts/rubric_authoring.py`; incomplete, non-numeric, or inconsistent grids
are refused.

The authoring contract is consumed by `scripts/make_rubric_package.py`. Its
successful package is deliberately rubric-only:

```text
imsmanifest.xml
orgunitconfig/orgunitconfig.xml
rubrics_d2l.xml
```

Activity attachment is outside this contract and remains manual and explicit.
