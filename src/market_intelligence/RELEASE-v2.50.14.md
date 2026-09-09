# Release v2.50.14

## Project deletion permissions

- Project deletion is now authorized through the project-admin scope.
- An `admin`/`assistant_admin` account can delete only explicitly assigned projects.
- Editors and viewers are denied by the API and do not receive a delete action in the UI.
