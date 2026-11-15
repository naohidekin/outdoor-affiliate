"""Select the latest verified public version without altering historical jobs."""
from datetime import datetime


def latest_published_jobs(jobs, on_invalid=None):
    groups = {}
    for job in jobs:
        publication = job.get('publication') or {}
        url = publication.get('url')
        if (not isinstance(url, str) or publication.get('verified') is not True
                or publication.get('revision') != job.get('revision')
                or (publication.get('readback') or {}).get('verified') is not True
                or publication['readback'].get('fingerprint') != job.get('revision')):
            continue
        groups.setdefault(url, []).append(job)
    def select(versions):
        dated = []
        for job in versions:
            value = job['publication'].get('at')
            if not isinstance(value, str):
                raise ValueError('publication_version_time_required')
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError('publication_version_aware_time_required')
            dated.append((stamp, job))
        newest = max(stamp for stamp, _ in dated)
        matches = [job for stamp, job in dated if stamp == newest]
        if len(matches) != 1:
            raise ValueError('publication_version_order_ambiguous')
        return matches[0]

    chosen = []
    for versions in groups.values():
        try:
            chosen.append(select(versions))
        except ValueError as error:
            if on_invalid is None:
                raise
            on_invalid(error, versions)
    return chosen
