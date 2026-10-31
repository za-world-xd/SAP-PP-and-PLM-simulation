export async function api(path, body, method = 'POST') {
    const response = await fetch(`/api${path}`, body === undefined ? undefined : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (response.status === 204)
        return undefined;
    let result;
    try {
        result = await response.json();
    }
    catch {
        throw new Error(`Expected JSON from the API (HTTP ${response.status}). Check the backend and API routing.`);
    }
    if (!response.ok) {
        const detail = result?.detail;
        throw new Error(Array.isArray(detail) ? detail.map((d) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ') : detail || `Request failed (${response.status})`);
    }
    return result;
}
export function today(offset = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}
export const key = () => crypto.randomUUID();
export const fmt = (value) => Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
