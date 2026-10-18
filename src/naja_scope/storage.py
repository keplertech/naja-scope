# SPDX-License-Identifier: Apache-2.0
"""Storage facts from raw sequential models and native DB0 memory primitives."""
from __future__ import annotations

from . import snl


def model_key(model):
    lib = model.getLibrary()
    return (lib.getDB().getID(), lib.getID(), model.getID())


def memory_info(instance):
    model = instance.getModel()
    lib = model.getLibrary()
    # NLDB0::isMemory uses the reserved DB0 MEMORY library. Do not classify
    # user modules by a suggestive name or WIDTH/DEPTH parameters alone.
    if not (model.isPrimitive() and lib.getDB().getID() == 0
            and lib.getName() == 'MEMORY'):
        return None

    def value(name):
        param = instance.getInstParameter(name)
        if param is None:
            param = model.getParameter(name)
        return param.getValue() if param is not None else None

    width, depth = int(value('WIDTH')), int(value('DEPTH'))
    writes = int(value('WR_PORTS'))
    initialized = bool(int(value('INIT_ENABLE')))
    info = {
        'instance': snl.inst_segment(instance),
        'model': model.getName(),
        'kind': 'rom' if writes == 0 else 'ram',
        'width': width, 'depth': depth, 'bits': width * depth,
        'read_ports': int(value('RD_PORTS')), 'write_ports': writes,
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
