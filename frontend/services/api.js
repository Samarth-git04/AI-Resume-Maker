const API_BASE_URL = "http://localhost:8000";

export async function getEditorConfig(filename) {
  const response = await fetch(
    `${API_BASE_URL}/documents/config/${encodeURIComponent(filename)}`
  );

  if (!response.ok) {
    throw new Error("Failed to load document editor configuration");
  }

  return response.json();
}

export function getResumeDownloadUrl(filename) {
  return `${API_BASE_URL}/documents/${encodeURIComponent(filename)}`;
}