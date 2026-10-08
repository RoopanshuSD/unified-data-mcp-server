| Metric | Result |
|---|---|
| Red-team attacks blocked by the SQL guard | **48/48** across 13 categories |
| Benign analyst queries wrongly rejected | **0/18** |
| Tool latency, end-to-end in-process (SQLite), 2000 calls | P50 1.43 ms · P95 2.51 ms |
| SQL guard alone (parse + AST checks) | P50 0.453 ms |
| `tools/list` size: this server vs one-tool-per-table (14 tables) | 5 tools / **784 tokens** vs 14 tools / 1368 tokens (cl100k_base) |
