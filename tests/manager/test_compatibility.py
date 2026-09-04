"""Fixed historical vendor facts, not a live latest-release lookup.

Source checked 2026-09-04:
https://firefox-source-docs.mozilla.org/testing/geckodriver/Support.html
Mozilla lists Gecko 0.33.0 with Firefox 102 ESR through 120. Refresh the wider
compatibility policy in Step 5; do not make offline tests fetch this web page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aselenium.manager import FirefoxDriverManager, FirefoxVersion, GeckoVersion


@pytest.mark.regression
@pytest.mark.parametrize("bound", ["min_firefox_version", "max_firefox_version"])
def test_gecko_033_historical_compatibility_bounds(tmp_path: Path, bound: Any) -> None:
    """Verify gecko 033 historical compatibility bounds.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        bound: Fixture or parametrized bound input for this regression.
    """
    manager = FirefoxDriverManager(directory=str(tmp_path))
    compatibility = manager._GECKODRIVER_TABLE[GeckoVersion("0.33.0")]
    if bound == "min_firefox_version":
        assert compatibility[bound] == FirefoxVersion("102.0.0")
    else:
        # Permit any representation of the upper end of Firefox 120, but not 121.
        assert FirefoxVersion("120") <= compatibility[bound] < FirefoxVersion("121")
