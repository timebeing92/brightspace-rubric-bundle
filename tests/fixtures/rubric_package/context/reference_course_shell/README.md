# Reference Course Shell Context

This folder is a tiny example of the **course context** the build script expects.

It contains:

- `imsmanifest.xml`
- `orgunitconfig/orgunitconfig.xml`

These are not the rubric payload files. They are the shell-context files used to tell the packager which Brightspace shell the generated package is targeting.

In real use, you would usually create a folder like this by extracting those two files from a real Brightspace export with:

```bash
python3 scripts/extract_course_context.py \
  --input /path/to/brightspace-export.zip \
  --output-dir build/course-context \
  --force
```
