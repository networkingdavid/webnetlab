import { api } from './client';

export interface Mib {
  id: number;
  name: string;
  filename: string;
  oid_count: number;
  parsed_at: string | null;
  created_at: string;
}

export interface MibOid {
  oid: string;
  name: string;
  syntax: string;
  access: string;
  description: string;
}

export const fetchMibs = (): Promise<Mib[]> =>
  api.get<Mib[]>('/api/mibs').then(r => r.data);

export const fetchMibOids = (id: number): Promise<MibOid[]> =>
  api.get<MibOid[]>(`/api/mibs/${id}/oids`).then(r => r.data);

export const uploadMib = (file: File): Promise<Mib> => {
  const form = new FormData();
  form.append('file', file);
  return api.post<Mib>('/api/mibs/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data);
};

export const assignMib = (mibId: number, deviceId: number): Promise<void> =>
  api.post(`/api/mibs/${mibId}/assign/${deviceId}`).then(() => undefined);

export const unassignMib = (mibId: number, deviceId: number): Promise<void> =>
  api.delete(`/api/mibs/${mibId}/assign/${deviceId}`).then(() => undefined);
