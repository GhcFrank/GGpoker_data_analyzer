# Repository instructions

### Testing policy

- During normal feature development, run ONLY the smallest test set directly related to the files or behavior being changed.
- Do NOT run the complete test suite by default. Do NOT run broad discovery such as `pytest`, `pytest tests`, `python -m unittest discover`, or equivalent full-suite commands unless the user explicitly requests it.
- Prefer one relevant test module, one test class, or individual tests. From the repository root, use `PYTHONPATH=poker_analyzer python3 -m unittest tests.test_<relevant_module>`.
- Add only the minimum tests necessary for new behavior or a regression. Prefer compact behavioral tests; do not create large numbers of speculative edge-case or helper-level tests.
- Full-suite validation is reserved for explicit release/final-validation requests that authorize it.
- The root `test/` directory contains hand-history sample data, not Python unit tests. Preserve useful fixtures.
