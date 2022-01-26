from __future__ import annotations
from common.rbg import RandomBatchGenerator as RBG
from common.utils import *
from common.packet import *
from abc import ABC, abstractclassmethod, abstractmethod
from dataclasses import dataclass, field
import hashlib, logging
from bitstring import BitArray

def packet_service(operation: Callable[..., T]) -> SimpyProcess[T]:
    """Wait for the Node's resource, perform the operation and wait a random service time."""
    def wrapper(self, *args):
        with self.in_queue.request() as res:
            yield res
            ans = operation(self, *args)
            service_time = self.rbg.get_exponential(self.serve_mean)
            yield self.env.timeout(service_time)
        return ans
    return wrapper

@dataclass
class Node(ABC):
    env: simpy.Environment = field(repr=False)
    name: str
    serve_mean: float = field(repr=False, default=0.8)
    timeout: int = field(repr=False, default=100.0)
    log_world_size: int = field(repr=False, default=10)
    

    id: int = field(init=False)
    ht: Dict[int, Any] = field(init=False)
    rbg: RBG = field(init=False, repr=False)
    in_queue: simpy.Resource = field(init=False, repr=False)

    @abstractmethod
    def __post_init__(self):
        self.id = Node._compute_key(self.name, self.log_world_size)
        self.ht = dict()
        self.rbg = RBG()
        self.in_queue = simpy.Resource(self.env, capacity=1)
        self.logger = logging.getLogger("logger")
        

    def log(self, msg: str, level: int = logging.DEBUG) -> None:
        self.logger.log(level, f"{self.env.now:5.1f} {self.name:8s}(id {self.id:3d}): {msg}")

    def _transmit(self) -> SimpyProcess:
        """Wait for the transmission delay of a message"""
        transmission_time = self.rbg.get_exponential(self.serve_mean)
        transmission_delay = self.env.timeout(transmission_time)
        yield transmission_delay

    def _req(self, process: SimpyProcess, packet: Packet, sent_req: simpy.Event) -> SimpyProcess:
        """Send a packet after waiting for the transmission time

        Args:
            process ([SimpyProcess]): the process to run
            packet (Packet): the packet to send
            sent_req (simpy.Event): the event to be triggered when done with the process
        """
        yield from self._transmit()
        yield self.env.process(process(packet, sent_req)) 

    def send_req(self, answer_method: SimpyProcess, packet: Packet) -> SimpyProcess[simpy.Event]:
        """Send a packet and bind it to a callback

        Args:
            answer_method (SimpyProcess): the callback to be called by the receiver
            packet (Packet): the packet to be sent

        Returns:
            simpy.Event: the request event that will be triggered by the receiver when it is done
        """
        self.log(f"sending packet {packet}...")
        sent_req = self.env.event()
        # transmission time
        self.env.process(self._req(answer_method, packet, sent_req))
        return sent_req

    def wait_resp(self, sent_req: simpy.Event) -> SimpyProcess[simpy.Event]:
        """Wait for the response of the recipient

        Args:
            sent_req (simpy.Event): the request associated to the wait event

        Returns:
            simpy.Event: the timeout event, which will be checked for processing in case it has elapsed
        """
        timeout = self.env.timeout(self.timeout)
        wait_event = timeout | sent_req
        yield wait_event
        self.log(f"received response")
        return timeout

    def _resp(self, recv_req: simpy.Event)-> SimpyProcess:
        """Trigger the event of reception after waiting for the trasmission delay

        Args:
            recv_req (simpy.Event): the reception event that has to be triggered
        """
        yield from self._transmit()
        recv_req.succeed()
        
    def send_resp(self, recv_req: simpy.Event) -> SimpyProcess:
        """Send the response to an event

        Args:
            recv_req (simpy.Event): the event to be processed
        """
        self.log(f"sending response...")
        self.env.process(self._resp(recv_req))


    @abstractmethod
    def find_node(self, key: int) -> Node:
        """Iteratively find the closest node(s) to the given key"""
        pass

    @abstractmethod
    def find_node_request(
        self,
        packet: Packet,
        recv_req: simpy.Event
    ) -> SimpyProcess[Node]:
        """Answer to a request for the node holding a given key"""
        pass

    @abstractmethod
    def on_find_node_request(
        self,
        packet: Packet,
        recv_req: simpy.Event
    ) -> SimpyProcess:
        """Answer with the node(s) closest to the key among the known ones"""
        pass

    @abstractmethod
    def join_network(self, to: Node) -> SimpyProcess:
        """Send necessary requests to join the network"""
        pass

    @staticmethod
    def _compute_key(key_str: str, log_world_size: int) -> int:
        digest = hashlib.sha256(bytes(key_str, "utf-8")).hexdigest()
        bindigest = BitArray(hex=digest).bin
        subbin = bindigest[:log_world_size]
        return BitArray(bin=subbin).uint

    @abstractclassmethod
    def _compute_distance(key1: int, key2: int, log_world_size: int) -> int:
        pass

    @abstractmethod
    def update(self):
        """Update finger table"""
        pass
    
    @abstractmethod
    def find_value(self, key: int):
        """Get value associated to a given key"""
        pass
    # to implement:
    # leave, (crash ?), store_value
