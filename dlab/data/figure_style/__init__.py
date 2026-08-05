"""
Vendored assets for the decision-lab house figure style.

These files are copied into session work directories by
``dlab.figure_style.install_figure_style``:

- ``matplotlibrc``       -> ``<work-dir>/_style/matplotlibrc``
- ``dlab_plotstyle.py``  -> ``<work-dir>/_style/dlab_plotstyle.py``
- ``SKILL.md``           -> ``<work-dir>/.opencode/skills/dlab-figure-style/SKILL.md``

``dlab_plotstyle.py`` imports matplotlib, which is not a dlab dependency —
it is only ever imported inside the sandbox (or by the test suite), never
by the dlab package itself.
"""
