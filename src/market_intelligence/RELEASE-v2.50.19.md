# Release v2.50.19

## Project deletion scope

- Project deletion is now checked against the current user's membership in that specific project.
- `admin` and `assistant_admin` accounts can delete only projects where they have an explicit `admin` or `assistant_admin` membership.
- Editors, analysts, and viewers cannot delete projects.
- The account owner remains the only account-wide exception.
- The API returns a per-project `can_delete` flag and the back office renders and guards the delete action from that flag, so projects outside the user's scope do not expose a usable delete button.
