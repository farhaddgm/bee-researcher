# Bee Researcher v2.80.0

## Approved roadmap scope

- MI-139: Toast messages now use the language direction: English appears at
  the bottom-right and Persian at the bottom-left.
- MI-140: every authenticated route uses the Assistant reference header shell,
  including the same spacing, controls, responsive behavior and account menu.
- MI-141: every signed-in user can upload a bounded profile image by clicking
  their sidebar avatar; the image is stored in account preferences and shown
  as a circular sidebar avatar for that user. Theme changes remain owner-only.
- MI-142: News List now shows score, state and action columns, starts with 15
  recent items, supports load-more pagination and a borderline-review filter.
  Borderline items require explicit owner approval and the API enforces a
  maximum of 10 such approvals per UTC day before publishing.

## Verification

- Python modules compile successfully.
- `git diff --check` passes.
- Docker image and service health are checked as part of deployment.
