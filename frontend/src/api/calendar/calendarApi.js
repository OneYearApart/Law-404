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

export async function saveCalendarConnection({
  connectionId,
  connectionName = null,
  googleEmail = null,
  provider = CALENDAR_PROVIDER,
}) {
  return apiRequest('/calendar/connection', {
    method: 'POST',
    body: {
      provider,
      connection_id: connectionId,
      connection_name: connectionName || connectionId,
      google_email: googleEmail || null,
      status: 'connected',
    },
  });
}

export async function deleteCalendarConnection(provider = CALENDAR_PROVIDER) {
  const params = new URLSearchParams({ provider });
  return apiRequest(`/calendar/connection?${params.toString()}`, {
    method: 'DELETE',
  });
}
