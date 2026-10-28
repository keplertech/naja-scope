# SPDX-License-Identifier: Apache-2.0
"""Storage facts from raw sequential models and native DB0 memory primitives."""
from __future__ import annotations

from . import snl


def model_key(model):
    lib = model.getLibrary()
    return (lib.getDB().getID(), lib.getID(), model.getID())


def memory_info(instance):
    model = instance.getModel()
    # Resolve native DB0 interfaces on the instance: dimensions can depend on
    # its parameters. Other libraries' memory models do not yet survive
    # naja-if reloads, so keep capacity summaries limited to DB0 primitives.
    if model.getLibrary().getDB().getID() != 0 or not model.hasMemoryInterface():
        return None
    interface = instance.getMemoryInterface()
    # Instance interfaces omit disconnected ports. Capacity and RAM/ROM
    # classification describe the cell, including its unused write ports.
    declared = model.getMemoryInterface()

    def value(name):
        param = instance.getInstParameter(name)
        if param is None:
            param = model.getParameter(name)
        return param.getValue() if param is not None else None

    width, depth = interface['width'], interface['depth']
    writes = len(declared['writePorts'])
    initialized = value('INIT_ENABLE') == '1'
    info = {
        'instance': snl.inst_segment(instance),
        'model': model.getName(),
        'kind': 'rom' if writes == 0 else 'ram',
        'width': width, 'depth': depth, 'bits': width * depth,
        'read_ports': len(declared['readPorts']), 'write_ports': writes,
        'address_bits': interface['abits'],
        'reset_mode': interface['resetMode'],
        'initialized': initialized,
    }
    if initialized:
        image = value('INIT')
        info['init_preview'] = image[:64]
        info['init_truncated'] = len(image) > 64
    return info


def register_bits(instance, static_cache):
    """Resolved flip-flop/latch states; None means no usable model.

    Call only for non-memory sequential cells. Instance resolution honors
    parameter-dependent models, rather than counting outputs (Q/QN alias).
    """
    model = instance.getModel()
    if model.hasSequentialModelFromParameters():
        resolved = instance.getSequentialModel()
        return len(resolved['states'])
    key = model_key(model)
    if key not in static_cache:
        static_cache[key] = (len(model.getSequentialModel()['states'])
                             if model.hasSequentialModel() else None)
    return static_cache[key]


COUNT_FIELDS = ('register_bits', 'register_bits_unknown_instances',
                'memory_instances', 'rom_instances', 'ram_instances', 'memory_bits')


def empty_counts():
    return dict.fromkeys(COUNT_FIELDS, 0)


def add_instance(counts, instance, static_cache):
    """Accumulate one direct child's storage; return memory detail if present."""
    memory = memory_info(instance)
    if memory is not None:
        counts['memory_instances'] += 1
        counts[memory['kind'] + '_instances'] += 1
        counts['memory_bits'] += memory['bits']
    elif instance.getModel().isSequential():
        bits = register_bits(instance, static_cache)
        if bits is None:
            counts['register_bits_unknown_instances'] += 1
        else:
            counts['register_bits'] += bits
    return memory
