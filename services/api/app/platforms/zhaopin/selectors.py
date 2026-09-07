from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZhaopinSelectors:
    """Centralized semantic fallbacks for user-visible 智联 pages.

    These are deliberately broad class-token candidates rather than a claim
    about one private DOM build. Real-page calibration belongs in this file.
    """

    job_cards: tuple[str, ...] = (
        ".joblist-box",
        ".job-list-item",
        ".job-card",
        ".job-item",
        "[data-job-id]",
        "[data-position-id]",
        "[data-zwid]",
    )
    title: tuple[str, ...] = (
        ".job-title",
        ".job-name",
        ".position-name",
        "[data-role='job-title']",
    )
    company: tuple[str, ...] = (
        ".company-name",
        ".company",
        ".com-name",
        "[data-role='company']",
    )
    salary: tuple[str, ...] = (
        ".salary",
        ".job-salary",
        ".sal",
        "[data-role='salary']",
    )
    location: tuple[str, ...] = (
        ".job-location",
        ".location",
        ".work-location",
        ".city",
        "[data-role='location']",
    )
    experience: tuple[str, ...] = (".experience", ".work-years", ".experience-requirement")
    education: tuple[str, ...] = (".education", ".degree", ".education-requirement")
    description: tuple[str, ...] = (
        ".job-desc",
        ".job-description",
        ".job-detail",
        ".description",
        "[data-role='job-description']",
    )


SELECTORS = ZhaopinSelectors()
