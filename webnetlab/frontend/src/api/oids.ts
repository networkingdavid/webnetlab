import { api } from './client';

export type ValueMode = 'static' | 'random' | 'scripted' | 'walk_seed';

export interface RandomConfig {
  min: number;
  max: number;
  type: 'integer' | 'counter' | 'gauge';
}

export interface OidValue {
  oid: string;
  value_mode: ValueMode;
  static_value: string | null;
  random_config: RandomConfig | null;
  script: string | null;
  walk_seed_value: string | null;
  updated_at: string;
}

export interface SetOidData {
  value_mode: ValueMode;
  static_value?: string | null;
  random_config?: RandomConfig | null;
  script?: string | null;
}

export interface OidUpdate {
  oid: string;
  value_mode: ValueMode;
  static_value?: string | null;
  random_config?: RandomConfig | null;
  script?: string | null;
}

export const fetchDeviceOids = (deviceId: number): Promise<OidValue[]> =>
  api.get<OidValue[]>(`/api/devices/${deviceId}/oids`).then(r => r.data);

export const setOid = (deviceId: number, oid: string, data: SetOidData): Promise<OidValue> =>
  api.put<OidValue>(`/api/devices/${deviceId}/oids/${encodeURIComponent(oid)}`, data).then(r => r.data);

export const deleteOid = (deviceId: number, oid: string): Promise<void> =>
  api.delete(`/api/devices/${deviceId}/oids/${encodeURIComponent(oid)}`).then(() => undefined);

export interface SeedResult {
  // preview=true fields
  preview?: { oid: string; value: string }[];
  parsed?: number;
  // preview=false fields
  seeded?: number;
  // both modes
  oids?: { oid: string; value: string }[];
  count?: number;
  format?: string;
}

export const seedDevice = (deviceId: number, file: File, preview = false): Promise<SeedResult> => {
  const form = new FormData();
  form.append('file', file);
  const params = preview ? '?preview=true' : '';
  return api.post(`/api/devices/${deviceId}/seed${params}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data);
};

export const bulkUpdateOids = (deviceId: number, updates: OidUpdate[]): Promise<void> =>
  api.post(`/api/devices/${deviceId}/oids/bulk`, { updates }).then(() => undefined);

/**
 * Download all OID values for a device as a seed JSON file.
 * Uses a hidden <a> click so the browser saves it with the correct filename
 * (Content-Disposition: attachment) returned by the server.
 */
export const exportDeviceOids = (deviceId: number, deviceName: string): void => {
  const url = `${api.defaults.baseURL}/api/devices/${deviceId}/oids/export`;
  const a = document.createElement('a');
  a.href = url;
  a.download = `${deviceName.replace(/\s+/g, '_')}_oids.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
};
