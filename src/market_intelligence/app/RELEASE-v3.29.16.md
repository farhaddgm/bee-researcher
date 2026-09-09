# Bee Researcher 3.29.16

## Media and Topics actions

- Media and Topics page-head buttons now share one deterministic action layer.
- Add, source suggestion, and health-check actions recover the first authorized workspace when clicked during initial loading.
- Topic creation is exposed through the same stable callback path as media creation.
- Media/topic row actions (enable/disable, settings, and delete) remain resolvable after CSP handler migration.
- Repeated clicks are guarded while an action is in progress.

