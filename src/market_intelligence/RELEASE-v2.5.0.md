# Bee Researcher v2.5.0

## Backoffice workspace management

- Added versioned assistant cloning with draft activation and recursive removal of credentials and Telegram destinations from copied configuration.
- Added explicit user-to-workspace membership with backend-enforced roles (`admin`, `assistant_admin`, `editor`, `analyst`, `viewer`).
- Added audit events for clone and membership assignment.
- Added a backoffice clone action so an administrator can start a new assistant from an existing workspace template.
- Added migration `0005_workspace_rbac` and regression coverage for template secret isolation.

Existing assistants remain unchanged; a clone always starts in `draft` and requires an explicit activation step.
