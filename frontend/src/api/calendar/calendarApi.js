import { apiRequest } from '../common/apiClient.js';

export const CALENDAR_PROVIDER = 'smithery_googlecalendar';

export async function getCalendarConnectionStatus(provider = CALENDAR_PROVIDER) {
  const params = new URLSearchParams({ provider });
  return apiRequest(`/calendar/connection?${params.toString()}`);
}

export async function getCalendarConnectGuide() {
  return apiRequest('/calendar/connect', {
    method: 'POST',
  });
}

export async function deleteCalendarConnection(provider = CALENDAR_PROVIDER) {
  const params = new URLSearchParams({ provider });
  return apiRequest(`/calendar/connection?${params.toString()}`, {
    method: 'DELETE',
  });
}
