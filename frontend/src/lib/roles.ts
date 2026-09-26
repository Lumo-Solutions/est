// Mirrors backend/app/core/enums.py::Role. The UI only uses this to decide
// what to show -- the server remains the only real enforcement.
export const Role = {
  ESTIMATOR: 'estimator',
  LEAD_ESTIMATOR: 'lead_estimator',
  PROCUREMENT_HEAD: 'procurement_head',
  BD_DIRECTOR: 'bd_director',
  MANAGING_DIRECTOR: 'managing_director',
  PLATFORM_ADMIN: 'platform_admin',
} as const

export type RoleName = (typeof Role)[keyof typeof Role]
