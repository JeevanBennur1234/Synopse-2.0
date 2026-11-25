const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const API_BASE_URL = RAW_BASE.replace(/\/+$/, "");

/**
 * Resolve a backend-relative URL (such as `/result/{job_id}/pages/0`)
 * against the configured API base URL, leaving data/blob/http URLs intact.
 */
export function resolveAssetUrl(pathOrUrl) {
  if (!pathOrUrl) return "";
  if (
    pathOrUrl.startsWith("http://") ||
    pathOrUrl.startsWith("https://") ||
    pathOrUrl.startsWith("data:") ||
    pathOrUrl.startsWith("blob:")
  ) {
    return pathOrUrl;
  }
  const normalized = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${API_BASE_URL}${normalized}`;
}

async function parseErrorDetail(response, fallback) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
  } catch {
    // Non-JSON error body
  }
  return fallback;
}

export async function checkHealth(signal) {
  const response = await fetch(`${API_BASE_URL}/health`, {
    method: "GET",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Health check failed (HTTP ${response.status})`);
  }
  return response.json();
}

export async function uploadDocument(file, signal) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/analyze`, {
    method: "POST",
    body: formData,
    signal,
  });

  if (!response.ok) {
    const detail = await parseErrorDetail(
      response,
      `Upload failed (HTTP ${response.status})`
    );
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }

  return response.json();
}

export async function getJobResult(jobId, signal) {
  const response = await fetch(
    `${API_BASE_URL}/result/${encodeURIComponent(jobId)}`,
    {
      method: "GET",
      signal,
    }
  );

  if (!response.ok) {
    const detail = await parseErrorDetail(
      response,
      `Failed to fetch analysis result (HTTP ${response.status})`
    );
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }

  return response.json();
}
