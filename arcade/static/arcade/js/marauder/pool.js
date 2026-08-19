// Fixed-capacity object pool. Pre-allocates entities and hands them out from a
// free stack, so steady-state gameplay allocates nothing (no GC hitches).
// Iterate the live entities with `pool.active` up to `pool.count`.

export class Pool {
    constructor(capacity, factory, reset) {
        this.capacity = capacity;
        this.reset = reset;
        this.active = new Array(capacity);
        this.count = 0;
        this._free = new Array(capacity);
        for (let i = 0; i < capacity; i++) this._free[i] = factory();
    }

    acquire() {
        if (this.count >= this.capacity) return null; // silently drop when full
        const obj = this._free[this.capacity - 1 - this.count];
        obj._alive = true;
        this.active[this.count] = obj;
        this.count++;
        return obj;
    }

    // Swap-remove the live entity at index i and return it to the free stack.
    releaseAt(i) {
        const obj = this.active[i];
        obj._alive = false;
        if (this.reset) this.reset(obj);
        const last = this.count - 1;
        this.active[i] = this.active[last];
        this.count--;
        this._free[this.capacity - 1 - this.count] = obj;
    }

    clear() {
        while (this.count > 0) this.releaseAt(this.count - 1);
    }
}
