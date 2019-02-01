"""Smarter-than-monkey testing for web apps.

You can read about APE and how to use it on its
[home page](https://boxingbeetle.com/tools/ape/).
What follows here is a quick tour of the code.

Overview
========

APE consists of a core that crawls the web app/site under test to
find pages to check. This core already does some checks, for example
it reports HTTP errors, checks for inconsistencies in text encoding
declarations and reports XML documents that are not well-formed.

When a document has been loaded, the core will offer it to all active
plugins to check. For example the HTML checker, even though it is core
functionality, is implemented as a plugin: `apetest.plugin.checkhtml`.

Entry Point
===========

`apetest.cmdline.main` parses command line arguments and then calls
`apetest.cmdline.run` to start a test run.

A test run starts by creating a `apetest.spider.Spider` to crawl the web
app/site under test, a `apetest.report.Scribe` to collect the reporting
and a `apetest.checker.PageChecker` to load and check the pages.

After all pages have been checked, the core writes the test report.
Finally, plugins are given a chance to create their final output
as well and clean up after themselves.


Key Concepts
============

Since APE has no specific knowledge about the app it is testing other than
its URL, it cannot test state changes. Therefore it will not attempt
to change any server-side state, by making only HTTP `GET` requests,
which should be idempotent.
The exact resource being requested is determined by the page URL and
an optional query; this is modeled by the `apetest.request.Request` class.

A request is discovered by crawling other pages. Something that can
generate requests is called a *referrer* and is modeled by the
`apetest.referrer.Referrer` class. Some referrers, like an HTTP redirect,
generate one exact request, while other referrers, like an HTML form,
can generate many different requests depending on the values of
the form's controls.

A request is considered *speculative* if an actual user accessing the web
app/site through a web browser would not normally generate it. The server
should be robust against such requests, but if it rejects them with
an HTTP "client error" (400) status, APE will not report that as an error.
"""
