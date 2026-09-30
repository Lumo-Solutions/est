import { Role } from '../../lib/roles'

// Mirrors backend/app/api/v1/routes/projects.py's _LOCATION_ROLES (project
// creation and member-adding have their own, wider lists there).
export const LOCATION_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
export const MEMBER_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.LEAD_ESTIMATOR]
// GET /users is restricted server-side (backend/app/api/v1/routes/users.py
// _READ_ROLES). Requesting it as an estimator was a guaranteed 403 -- a
// console error on every project page, previously masked by e2e timing.
export const USER_DIRECTORY_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
