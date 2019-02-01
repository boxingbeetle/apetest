APE - Automated Page Exerciser
==============================

*Smarter-than-monkey testing for web apps*

<https://boxingbeetle.com/tools/ape/>

Testing Without Test Scripts
----------------------------

The only thing APE needs to know about a web app or site is its URL. From that starting point, it automatically finds links to other pages and subjects all of them to a series of checks. So it takes very little effort to check your web app or site with APE.

Of course, since APE knows next to nothing about your specific web app, there are limits to what it can check. For example, it can submit a form and check whether the server returns an error or an OK result and whether the resulting page is valid HTML, but it cannot check whether the content matches the submitted form values. Therefore, APE is not a replacement for scripted test tools like [Selenium](https://docs.seleniumhq.org/).

You may be surprised by how many problems can be uncovered just following random links and checking the result. Give APE a try!

Can APE Test My Web App/Site?
-----------------------------

APE can be used if:

- you have a static web site, for example one written by hand or generated by a static content management system like [Lektor](https://www.getlektor.com/) or [Jekyll](https://jekyllrb.com/)
- you have a dynamic web application in which URLs are meaningful and the main content is in HTML

APE cannot be used if:

- your server relies on session state instead of HTTP GET requests to determine what to render
- your web app generates all HTML in client-side JavaScript instead of serving it over HTTP

So roughly, APE will work if your app supports deep-linking and JavaScript is used for optional enhancements, while APE will not work if you have built a single-page application.

Installation
------------

To install use pip:

    $ pip install apetest

Now you should be able to run the `apetest` command:

    $ apetest --version
    APE 0.1.0

APE uses the [Nu Html Checker (v.Nu)](<https://validator.github.io/>) to check HTML. The checker itself is installed by pip, but you also need a Java runtime on your machine to run it, such as [OpenJDK](https://openjdk.java.net/install/index.html). You only need the runtime (JRE) and not the full development kit (JDK).

You can use APE without the HTML checker, but it is much more useful with the checker enabled.

Usage
-----

To check the HTML of a static web site in a local directory:

    $ apetest --check launch website/ report.html

To do a quick sanity check (no HTML check) of a web application in development:

    $ apetest localhost:8080 report.html

To see all command line options:

    $ apetest --help

How Mature Is APE?
------------------

It is mature enough that I'm using it in production to test our company web site and the web application SoftFab that we'll be releasing soon. However, at the time of writing I am the only user, so I fully expect that once other people start using it, they will run into bugs and limitations that I haven't. If that happens to you, please let me know (see next section).

The code was modernized over the last few months and should be in reasonable shape. It is fully documented and free of issues PyLint can detect. It is missing unit tests for most of its functionality though, so I'm relying on system tests at the moment, which can easily miss corner cases.

Feedback
--------

You can report bugs and make feature requests in [APE's issue tracker at GitHub](https://github.com/boxingbeetle/apetest/issues).

If you are interested in sponsoring a new feature, [contact us at Boxing Beetle](https://boxingbeetle.com/contact/).

Writing a Plugin
----------------

APE can be extended using plugins. Plugins are Python modules placed into the `apetest.plugin` package; read the API documentation of `apetest.plugin` to learn about the plugin interface.

The plugin interface was designed to have just enough features to be able to convert pre-existing optional functionality to plugins. The intention is to grow and improve it over time. So if you need additional callbacks or information passed, feel free to request a change in the plugin interface, or prototype one yourself (see next section).

Contributing
------------

If you want to modify APE, start by cloning the Git repository:

    $ git clone https://github.com/boxingbeetle/apetest.git

Make sure the `python` command starts Python version 3.5 or later. If this is not the default on your system, you can use for example [pyenv](https://github.com/pyenv/pyenv) or [virtualenv](https://virtualenv.pypa.io/) to set up an environment with the right Python version.

APE uses the [Poetry build system](https://poetry.eustace.io/) for managing its development environment. Using the [recommended installation procedure](https://github.com/sdispater/poetry#installation) instead of pip helps separate Poetry's dependencies from those of the software it manages, like APE.

Start a shell in the virtual environment managed by Poetry:

    $ poetry shell

Install APE and its runtime and development dependencies:

    $ poetry install

Now you should have an `apetest` command available in the Poetry shell that runs APE directly from the source tree. This means that any code you edit is immediately active, for easy testing.

There is a `Makefile` with a few useful developer commands. The target you will probably want to make first is `docs`, which generates the documentation files:

    $ make docs

Now you can read the API documentation in `docs/api/`. The documentation of the top-level module gives a quick overview of the code.

Before submitting a pull request, please run `make lint` to have PyLint check the code. There should be zero warnings. If PyLint detects any false positives, please add a `pylint: disable=<id>` comment to suppress them. When PyLint is statisfied, use `make test` to run the available tests.