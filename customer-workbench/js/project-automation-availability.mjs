// Both production backends lack automation-projects and automation-health routes.
// Keep the integration code, but enable it only after both API contracts ship.
// This release switch does not grant access; existing identity checks still apply.
export const projectAutomationAvailable=false;
