import logging

from sales.services.dibbs_notices import check_dibbs_notices

logger = logging.getLogger(__name__)


def run():
    """Scrape DIBBS homepage for new public notices and persist them."""
    result = check_dibbs_notices()
    if result.get("error"):
        logger.warning(
            "check_dibbs_notices: finished with error=%s", result["error"]
        )
    else:
        logger.info(
            "check_dibbs_notices: finished. new_notices=%d",
            result.get("created", 0),
        )
