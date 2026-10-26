# LinkedIn Announcer

Fifth workflow tab at `/linkedin`. Existing Quote Generator clients are shared, not duplicated.
The nullable `clients.linkedin_profile` JSON column stores the company page, voice, audience,
approved public background, example posts, hashtags and confirmed profile contacts. Alembic
revision `f5a7b9c1d3e6` adds the column after production revision `c3e5f7a9b1d2`; apply migrations before starting the new backend.
The same profile editor appears in Quote Generator and the announcer. Other quote data and
saved style/background remain available; LinkedIn examples do not pollute sample media quotes.

Paste substantive coverage text; URL is optional and is not fetched. Publisher, journalist,
angle and length are optional per-post inputs. The existing OpenRouter configuration generates
an editable draft. No LinkedIn account connection or publishing is performed. The exact provided
article URL is appended once. Generation failures are surfaced, with no fabricated fallback.

## Research, reviewed 26 October 2026

Direct retrieval of the OXCCU company home was blocked by LinkedIn. Public indexed material
provided these examples; this is not a complete audit of the company feed or performance:

- Andrew Symes' SVT coverage announcement names the broadcaster, credits Johan Bergendorff and
  Olof Andersson, specifies OX1's role in the programme and links to the film:
  https://www.linkedin.com/posts/symesandrew_todayoxccu-tech-ltdwas-featured-in-a-documentary-activity-7441871516021100545-A9an
- Jane Jin's Future of Flight announcement connects the feature to the company mission and
  acknowledges directly involved contributors:
  https://www.linkedin.com/posts/janejin_sustainability-saf-sustainableaviationfuel-activity-7481441572505595904-75NC

These support the editorial pattern: coverage + concrete takeaway + relevant credit + reading link.
They do not prove that a specific format generates more engagement.

Primary guidance:

- LinkedIn's engaging-post guide recommends a main idea, supporting detail, own perspective,
  readable line breaks, relevant tags and a clear call to action:
  https://www.linkedin.com/business/talent/blog/talent-acquisition/how-to-write-engaging-post-in-linkedin-feed
- LinkedIn's Page content guide recommends crediting authors and companies for third-party content:
  https://www.linkedin.com/business/marketing/blog/linkedin-pages/10-content-ideas-for-your-linkedin-page
- LinkedIn's feed guidance recommends thoughtful mentions and focused hashtags. It is from 2019;
  the product's cap of five suggested mentions and three hashtags is an editorial default, not an
  asserted current ranking rule:
  https://news.linkedin.com/2019/January/what-s-in-your-linkedin-feed--people-you-know--talking-about-thi

No unsupported algorithm claims about links in comments, optimal posting times or guaranteed reach
are baked into the generator. Short and Standard word ranges are product choices. Users should
check source accuracy and use images/clippings only with appropriate reproduction rights.

## Tagging: what is automatic

Match saved exact contact names against the supplied coverage and attribution, with word boundaries,
case-insensitive matching, URL deduplication and a five-contact cap. Return names, verified-by-user
saved URLs, roles and match reasons separately from post copy. Do not infer handles or identity from
names. No broad scraping or personal profile discovery occurs.

Plain-text copy/paste does not activate mentions. The user types @ and selects the matching account
in LinkedIn; some accounts disable mentions:
https://www.linkedin.com/help/linkedin/answer/a525082/mention-people-in-your-posts

Full automatic live tagging would require an authorized publishing integration, appropriate LinkedIn
permissions and actual person/organization URNs with correct display names. A vanity URL is not a URN.
That integration is outside this copy-generation feature:
https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-06

## Validation

`pytest tests/test_linkedin.py` uses an isolated SQLite client table and mocked provider, never production.
Frontend build and focused TypeScript checks cover the new components. Live provider quality and
production verification require deployment access and configured OpenRouter credentials.

Release is based on production master and excludes Phase 1 staging changes. When merging into the staging branch, reconcile the existing LinkedIn migration parent with its Phase 1 migration before upgrading. LinkedIn generation uses the existing expensive-request rate and concurrency limits.
