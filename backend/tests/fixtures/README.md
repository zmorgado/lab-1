# Test fixtures

Real source files, copied byte for byte, so the AST tests (#20) run against code
as it exists on GitHub rather than against invented trees. The `.txt` suffix
keeps them from being imported, collected or linted as part of the backend.

| File | Source | License |
| --- | --- | --- |
| `cpython_bisect.py.txt` | CPython 3.12.8, `Lib/bisect.py` | PSF License |
| `cpython_textwrap.py.txt` | CPython 3.12.8, `Lib/textwrap.py` | PSF License |
| `cpython_numbers.py.txt` | CPython 3.12.8, `Lib/numbers.py` | PSF License |
| `cookiecutter_users_models.py.txt` | [cookiecutter/cookiecutter-django](https://github.com/cookiecutter/cookiecutter-django) @ `b8aaba5`, `{{cookiecutter.project_slug}}/{{cookiecutter.project_slug}}/users/models.py` | BSD-3-Clause |

Each one covers a case the tests need:

- **bisect**: four small top-level functions, a clean survivor set.
- **textwrap**: a class with methods, nested functions inside `indent`, and
  `_wrap_chunks`, which is far longer than any snippet worth comparing.
- **numbers**: abstract methods whose body is only a docstring or
  `raise NotImplementedError`.
- **cookiecutter**: a Jinja-templated `.py` file. GitHub indexes it as Python, but
  it does not parse as Python.
