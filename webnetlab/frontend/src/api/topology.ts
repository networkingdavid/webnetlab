import axios from 'axios';
import type { TopologyData, TopologyLink } from '../types/topology';

const BASE = 'http://localhost:8000';

export const fetchTopology = (): Promise<TopologyData> =>
  axios.get<TopologyData>(`${BASE}/api/topology`).then(r => r.data);

export const createLink = (data: {
  src_device_id: number;
  src_interface: string;
  dst_device_id: number;
  dst_interface: string;
}): Promise<TopologyLink> =>
  axios.post<TopologyLink>(`${BASE}/api/topology/links`, data).then(r => r.data);

export const deleteLink = (id: number): Promise<void> =>
  axios.delete(`${BASE}/api/topology/links/${id}`).then(() => undefined);
