import { api } from './client';

export interface Device {
  id: number;
  name: string;
  type: 'router' | 'switch' | 'server' | 'generic';
  ip_address: string;
  mac_address: string | null;
  network_id: number | null;
  docker_container_id: string | null;
  status: 'running' | 'stopped' | 'error';
  snmp_community: string;
  snmp_port: number | null;
  created_at: string;
  updated_at: string;
}

export interface CreateDeviceData {
  name: string;
  type: 'router' | 'switch' | 'server' | 'generic';
  ip_address: string;
  mac_address?: string;
  network_id?: number;
  snmp_community?: string;
  snmp_port?: number;
}

export interface BulkCreateDeviceData {
  base_ip: string;
  count: number;
  name_prefix: string;
  network_id?: number;
  type?: 'router' | 'switch' | 'server' | 'generic';
  snmp_community?: string;
}

export const fetchDevices = (): Promise<Device[]> =>
  api.get<Device[]>('/api/devices').then(r => r.data);

export const fetchDevice = (id: number): Promise<Device> =>
  api.get<Device>(`/api/devices/${id}`).then(r => r.data);

export const createDevice = (data: CreateDeviceData): Promise<Device> =>
  api.post<Device>('/api/devices', data).then(r => r.data);

export const bulkCreateDevices = (data: BulkCreateDeviceData): Promise<Device[]> =>
  api.post<Device[]>('/api/devices/bulk', data).then(r => r.data);

export const deleteDevice = (id: number): Promise<void> =>
  api.delete(`/api/devices/${id}`).then(() => undefined);

export const startDevice = (id: number): Promise<Device> =>
  api.post<Device>(`/api/devices/${id}/start`).then(r => r.data);

export const stopDevice = (id: number): Promise<Device> =>
  api.post<Device>(`/api/devices/${id}/stop`).then(r => r.data);

export const restartDevice = (id: number): Promise<Device> =>
  api.post<Device>(`/api/devices/${id}/restart`).then(r => r.data);
