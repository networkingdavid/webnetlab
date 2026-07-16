export interface TopologyNode {
  id: number;
  name: string;
  type: string;
  ip_address: string;
  status: string;
  interfaces: string[];
}

export interface TopologyLink {
  id: number;
  src_device_id: number;
  src_interface: string;
  dst_device_id: number;
  dst_interface: string;
  docker_network_id: string | null;
}

export interface TopologyData {
  nodes: TopologyNode[];
  links: TopologyLink[];
}
