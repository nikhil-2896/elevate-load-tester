# 1 Concept: target analysis

> [!NOTE]
> This concept is subject to refinement during the
> development process. Until the contract exists, and
> wherever it is silent, this page is the source of
> truth.

## The goal

A tester gives a URL and learns, before any load is sent, whether it is **well-formed**, whether it **answers**, whether it is an **API or a website**, and (for a website) **which pages** to test.

## The people

- **tester**: types a URL, reads the verdict, decides what to run
- **the target**: is probed lightly (HEAD/GET/POST once each at most)
- **the next feature**: load-test dispatch, which takes the analysis' paths

## The things

- **sanity result**: `valid_format`, `reachable`, `status_code`, `final_url`, `headers`
- **classification**: `api` | `website` | `unknown`, with a confidence 0–1
- **sitemap**: `/sitemap.xml` of the host, if there is one
- **page paths**: up to 20 real pages from the sitemap

## The rules

1. Only absolute `http`/`https` URLs with a host are well-formed; a malformed URL is never fetched
2. A server that **answers at all below 500** is reachable, even with 404/405: many POST-only API endpoints refuse HEAD and GET
3. A 5xx, or no connection, is **not** reachable
4. JSON content type says API; HTML says website; an API-looking path (`/api/`, `/v1/`…) leans API; no signal is `unknown` with confidence 0
5. Only a **website** is asked for a sitemap
6. A sitemap's pages exclude assets (images, CSS, JS, PDFs, XML, icons)
7. A **sitemap index** is followed **one level** (first 5 sub-sitemaps), never deeper
8. Malformed XML gives no pages, not an error

## What it will not do

Crawl links, execute JavaScript, read `robots.txt`, or classify by body content. It does not authenticate.

## The artefact

```
URL ─ well-formed? ─no→ 400
          │yes
      reachable? ─no→ 400 (sanity returned)
          │yes
      classify ── website → + sitemap → paths
               └─ api / unknown → verdict only
```
