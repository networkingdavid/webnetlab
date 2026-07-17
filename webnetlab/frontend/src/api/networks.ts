import { api } from './client';

export interface Network {
  id: number;
  name: string;
  type: 'bridge' | 'macvlan' | 'nat' | 'host-bridge' | 'ipvlan';
  subnet: string | null;
  gateway: string | null;
  docker_network_id: string | null;
  host_interface: string | null;
  created_at: string;
}

export interface CreateNetworkData {
  name: string;
  type: 'bridge' | 'macvlan' | 'nat' | 'host-bridge' | 'ipvlan';
  subnet: string;
  gateway: string;
  host_interface?: string;
}

export interface HostInterface {
  name: string;
  mac: string;
  state: 'up' | 'down' | 'unknown';
  speed_mbps: number;   // 0 = unknown
  ip: string;           // primary IPv4, '' if unknown
  rx_bytes: number;
  tx_bytes: number;
}

export const fetchNetworks = (): Promise<Network[]> =>
  api.get<Network[]>('/api/networks').then(r => r.data);

export const createNetwork = (data: CreateNetworkData): Promise<Network> =>
  api.post<Network>('/api/networks', data).then(r => r.data);

export const deleteNetwork = (id: number): Promise<void> =>
  api.delete(`/api/networks/${id}`).then(() => undefined);

export const fetchHostInterfaces = (): Promise<HostInterface[]> =>
  api.get<{ interfaces: HostInterface[] }>('/api/networks/interfaces')
    .then(r => r.data.interfaces);
