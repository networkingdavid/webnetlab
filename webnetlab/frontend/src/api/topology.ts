import type { TopologyData, TopologyLink } from '../types/topology';
import { api } from './client';

export const fetchTopology = (): Promise<TopologyData> =>
  api.get<TopologyData>('/api/topology').then(r => r.data);

export const createLink = (data: {
  src_device_id: number;
  src_interface: string;
  dst_device_id: number;
  dst_interface: string;
}): Promise<TopologyLink> =>
  api.post<TopologyLink>('/api/topology/links', data).then(r => r.data);

export const deleteLink = (id: number): Promise<void> =>
  api.delete(`/api/topology/links/${id}`).then(() => undefined);
