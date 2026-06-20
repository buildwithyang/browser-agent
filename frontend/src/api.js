// 网关基础地址；登录态走 cookie，所有请求都带 credentials。
// 默认 "/api"：开发时由 Vite 反向代理到网关（同源，无跨域）；生产构建时把
// VITE_GATEWAY_URL 设为网关绝对地址（前端为纯静态、没有 Vite 代理）。
const GATEWAY = (import.meta.env.VITE_GATEWAY_URL || "/api").replace(/\/+$/, "");

// 登录是整页跳转（要经 Casdoor 再跳回），同样走同源 /api，cookie 才落在前端这边。
export const loginUrl = `${GATEWAY}/auth/login`;

async function call(path, { method = "GET", body } = {}) {
  const res = await fetch(`${GATEWAY}${path}`, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    const err = new Error("未登录");
    err.code = 401;
    throw err;
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    throw new Error((data && data.detail) || `请求失败 (${res.status})`);
  }
  // 后端统一 ApiResponse{ code, message, data }；/auth/me 等也是这个结构。
  return data && "data" in data ? data.data : data;
}

export function fetchMe() {
  return call("/auth/me");
}

export function issueExtensionToken() {
  return call("/auth/extension-token", { method: "POST" });
}

export function logout() {
  return call("/auth/logout", { method: "POST" });
}

export function listResumes() {
  return call("/resumes").then((d) => (d && d.items) || []);
}

export function activateResume(id) {
  return call(`/resumes/${id}/activate`, { method: "POST" });
}

export function deleteResume(id) {
  return call(`/resumes/${id}`, { method: "DELETE" });
}

// 完整上传流程：签发预签名地址 -> 直传 OSS -> 通知后端解析入库。
export async function uploadResume(file, onStage) {
  onStage && onStage("signing");
  const { object_key, upload_url } = await call("/resumes/upload-url", {
    method: "POST",
    body: { filename: file.name, content_type: file.type || "application/pdf" },
  });

  onStage && onStage("uploading");
  const put = await fetch(upload_url, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/pdf" },
    body: file,
  });
  if (!put.ok) {
    throw new Error(`上传到对象存储失败 (${put.status})`);
  }
  const etag = (put.headers.get("ETag") || "").replaceAll('"', "") || null;

  onStage && onStage("parsing");
  const { resume } = await call("/resumes/complete-upload", {
    method: "POST",
    body: {
      object_key,
      filename: file.name,
      content_type: file.type || "application/pdf",
      file_size: file.size,
      etag,
    },
  });
  return resume;
}
