---
name: resume-docx
description: Create, rewrite, tailor, and optimize resumes, especially when Codex needs to generate or update Word (.docx) resumes from raw candidate notes, existing resumes, target job descriptions, or fixed-layout Word templates. Use when asked to draft a new resume, improve resume bullets, adapt a resume to a JD, inspect text-box-heavy templates, extract text from a .docx resume for review, or export the final result back to .docx. Prefer this skill when the workspace uses Conda-managed Python environments.
---

# Resume Docx

## Quick Start

1. Detect the active Conda environment before running Python or installing packages. Read `references/conda-environment.md`.
2. If the user provides an existing `.docx` resume, extract it first:
   `python scripts/resume_docx.py extract --input path/to/resume.docx --output extracted.md`
3. Improve the content against `references/resume-optimization.md`.
4. Build the final Word file:
   `python scripts/resume_docx.py create --input references/resume-spec-example.json --output resume.docx`
5. If the user provides a fixed-layout Word template, inspect it first:
   `python scripts/resume_docx.py inspect-template --input template.docx --output layout.json`
6. For text-box-heavy templates, rebuild the resume into a controlled two-page document:
   `python scripts/resume_docx.py fill-template --template template.docx --source resume.docx --target-role 产品运营 --remove-photo --output tailored-resume.docx`

## Workflow

### Draft A New Resume

- Collect the target role, summary, experience, projects, education, skills, and links.
- Convert the information into the JSON shape shown in `references/resume-spec-example.json`.
- Generate the Word file with `scripts/resume_docx.py create`.
- Re-open the exported file with `extract` if quick validation is needed.

### Optimize An Existing Resume

- If the source is `.docx`, run `extract` first.
- Review the text against `references/resume-optimization.md`.
- Rewrite the weakest sections first: summary, most recent experience, achievements, and skills.
- Preserve factual accuracy. Do not invent metrics, titles, employers, or dates.
- If a JD exists, mirror important terminology truthfully and remove irrelevant bullets.
- Export the improved version back to `.docx` with `create`.

### Tailor To A Job Description

- Compare the JD against the current resume.
- Prioritize missing keywords, weak achievements, vague summaries, and outdated tools.
- Prefer bullets that show action, scope, method, and result.
- Keep the document concise unless the user explicitly asks for a longer format.

### Rebuild From A Fixed Template

- Inspect the template with `inspect-template` before deciding how to edit it.
- Treat templates dominated by `w:txbxContent`, `wps:wsp`, anchored drawings, or stock images as fixed-layout documents.
- Do not attempt paragraph-level in-place replacement for those files unless the text is already tightly controlled and the layout has spare capacity.
- Prefer `fill-template` to extract the template's visual tokens, optimize the source resume, and generate a controlled 1-2 page result that keeps the template's visual language without reusing irrelevant stock content.
- When `--remove-photo` is present, omit the template's stock portrait instead of carrying it into the output.

## Conda Rules

- Treat Conda as the source of truth for Python version management in this workspace.
- Prefer the active Conda environment instead of system Python or ad-hoc virtualenvs.
- Inspect the environment before changing dependencies:
  `echo $CONDA_DEFAULT_ENV`
  `python -c "import sys; print(sys.executable)"`
  `conda info --envs`
- Install missing Python packages into the intended Conda environment:
  - Active env: `python -m pip install python-docx`
  - Non-activated env: `conda run -n <env> python -m pip install python-docx`
- Re-verify imports after installation:
  `python -c "import docx; print(docx.__version__)"`
- Avoid `sudo pip`, avoid mixing multiple Python interpreters, and do not assume `base` unless the shell shows it is active.

## Document Schema Notes

- Use top-level fields such as `name`, `title`, `location`, `email`, `phone`, `website`, `linkedin`, `github`, `summary`, and `sections`.
- Use `sections[].items[]` for experience, projects, education, certifications, or skill groups.
- Use string items for simple bullet lists.
- Use objects with `title`, `company`, `location`, `date`, `subtitle`, `bullets`, `text`, `label`, and `value` when richer formatting is needed.
- Start from `references/resume-spec-example.json` instead of inventing a new shape.

## Resources

- `scripts/resume_docx.py`: Create `.docx` resumes from JSON, extract text from existing `.docx` resumes, inspect fixed-layout templates, and generate optimized two-page outputs from template + source files.
- `references/resume-optimization.md`: Compact guidance for improving ATS match, clarity, and impact.
- `references/conda-environment.md`: Workspace-specific Python and Conda operating rules.
- `references/resume-spec-example.json`: Example input for document generation.
