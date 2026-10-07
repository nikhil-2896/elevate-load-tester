# 5 Refinement: target analysis

## Turn 1 (retrofit)

**T2.\*: 20 of 20 passed on first run.** No code change.

The sitemap-index tests (T2.15, T2.16) pin down a bug found earlier by hand: an index lists *other sitemaps*, not pages, and used to leak `.xml` paths into the load test.

| Sign | Points to | Action |
| ---- | --------- | ------ |
| HTML (0.7) outweighs an API-looking path (0.6) | the concept | A page of HTML at `/api/docs` is called a website. The contract says the path "leans", it does not decide |
| Concept says "never fetched" for malformed URLs | tests | T2.1 checks the result; it does not prove no call was made: add a spy in the next turn |

## Next turn (concept first)

- A site whose sitemap is only in `robots.txt`: a missing rule
- Redirects: `final_url` is returned but the sitemap is looked up on the *original* host
