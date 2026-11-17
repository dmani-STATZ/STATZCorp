"""Single source for CLIN pod_status. Do not recompute this inline."""


def compute_pod_status(clin, shipments=None) -> str:
    """Return ``full``, ``partial``, or ``none``.

    ``pod_complete`` True is ``full``. Otherwise ``none`` when no shipment has
    a ``pod_date`` (including zero shipments), else ``partial``.

    Pass ``shipments`` to use that iterable and skip another query. When it is
    omitted, shipment POD dates are loaded once.
    """
    if clin.pod_complete:
        return "full"
    if shipments is None:
        pod_dates = list(clin.shipments.values_list("pod_date", flat=True))
    else:
        pod_dates = [shipment.pod_date for shipment in shipments]
    if any(pod_date is not None for pod_date in pod_dates):
        return "partial"
    return "none"
