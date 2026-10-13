# Test fixtures

Real content, pasted exactly as it arrives from LinkedIn, so parsers are tested against
what users actually paste — including the flattened whitespace and glued links
(`https://lnkd.in/euyuNU9yPart 1:`) that copy-paste produces.

- `semantic_caching_part3/` — an article by the project author and its announcement post,
  used with permission.
- `comments/caching_thread.txt` — a comment section in the exact shape LinkedIn's copy
  produces (connection markers, "Author" badge, headlines, ages, Like/Reply noise), with
  invented people.

Fixtures must never contain other people's comments or profile data. Use invented names
(`Jane Example`, `linkedin.com/in/jane-example`) for comment fixtures.
