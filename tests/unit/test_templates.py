"""Every page template compiles, so a Jinja syntax error fails before a page renders it."""

import pytest

from dots_and_dashes.web import templates


@pytest.mark.parametrize("name", templates.env.list_templates(extensions=["html"]))
def test_the_template_compiles(name):
    templates.env.get_template(name)
