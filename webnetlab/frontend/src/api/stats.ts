import { api } from './client';

export interface Stats {
  devices: number;
  devices_running?: number;
  networks: number;
  mibs?: number;
  snmp_queries: number;
}

export const fetchStats = (): Promise<Stats> =>
  api.get<Stats>('/api/stats').then(r => r.data);
