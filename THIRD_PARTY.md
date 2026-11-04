# Third-party components and branding

Application code uses FastAPI, Starlette, Uvicorn, Pydantic and optional NumPy, SciPy, scikit-learn,
joblib and threadpoolctl. Development tests additionally use pytest, httpx and Playwright. Review
and comply with each installed distribution's license and notice requirements before redistribution.
The application does not bundle their binaries, pretrained vendor models or market-data licenses.

The entry/exit/replay workflow was informed by reviewing Jake Schincariol's MIT-licensed
day-trader-skill repository (https://github.com/Jakeschincariol/day-trader-skill).
India Quant's new toolkit is independently implemented for its own Indian-market data,
SQLite store and browser interface; that plugin and its broker executor are not bundled.
Headlines are retrieved on demand from Google News RSS. Publisher names and links are
shown; article text is not reproduced and the news feed is not an official exchange feed.

No external fonts, CDN assets or commercial charting library are bundled. The interface uses local
CSS/JavaScript and SVG. Product names in the research document identify third-party products and
do not imply affiliation, endorsement or use of their proprietary algorithms.

India Quant is a working project name, not a trademark-availability assertion. Check naming rights
before launching a business. User/imported market data remains subject to its own contract and rights.
