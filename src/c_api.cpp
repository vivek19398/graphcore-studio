#include "graphcore/c_api.h"
#include "graphcore/graphcore.hpp"
#include <memory>
using namespace graphcore;
struct gc_handle {
    GraphBuilder builder;
    std::map<std::string,std::vector<std::string>> edges;
    std::string error, wire;
    Snapshot result;
    std::atomic<bool> cancelled{false};
    gc_event_callback observer = nullptr;
    void* observer_data = nullptr;
    explicit gc_handle(const char* v) : builder(v) {}
};
namespace {
struct Reply { NodeResult result; std::string error; };
template<class F> int guard(gc_handle* h,F fn) noexcept {
    if(!h) return -1;
    try { h->error.clear(); fn(); return 0; }
    catch(const std::exception& e) { try { h->error=e.what(); } catch(...) {} }
    catch(...) { try { h->error="Unknown native error"; } catch(...) {} }
    return -1;
}
template<class F> int reply_guard(void* p,F fn) noexcept {
    if(!p) return -1;
    try { fn(*static_cast<Reply*>(p)); return 0; } catch(...) { return -1; }
}
void required(const char* s) { if(!s) throw Error("Required string is null"); }
}
extern "C" {
int gc_set_observer(gc_handle* h,gc_event_callback fn,void* data) {
    return guard(h,[&] { h->observer=fn; h->observer_data=data; });
}
void gc_cancel(gc_handle* h) { if(h) h->cancelled.store(true); }
int gc_add_condition(gc_handle* h,const char* name,const char* key,const char* expected,const char* yes,const char* no) {
    return guard(h,[&] {
        required(name); required(key); required(expected); required(yes); required(no);
        std::string k(key),value(expected),a(yes),b(no);
        h->builder.add_node(name,[k,value,a,b](const State& s,const Context&) {
            const auto it=s.find(k);
            if(it==s.end()) throw Error("Condition state field is missing: "+k);
            return NodeResult{{},it->second==value?a:b};
        });
        h->edges[name]={a,b};
    });
}
gc_handle* gc_create(const char* v) { try { required(v); return new gc_handle(v); } catch(...) { return nullptr; } }
void gc_destroy(gc_handle* h) { delete h; }
const char* gc_error(gc_handle* h) { return h?h->error.c_str():"Null handle"; }
int gc_add_node(gc_handle* h,const char* name,gc_callback fn,void* user,unsigned retries) {
    return guard(h,[&] {
        required(name); if(!fn) throw Error("Null callback");
        h->builder.add_node(name,[fn,user](const State& state,const Context& ctx) {
            Reply reply; auto wire=encode_state(state);
            auto code=fn(wire.c_str(),ctx.resumed,ctx.response.c_str(),&reply,user);
            if(code || !reply.error.empty()) throw Error(reply.error.empty()?"Python callback failed":reply.error);
            return reply.result;
        },{retries});
    });
}
int gc_add_edge(gc_handle* h,const char* source,const char* target) {
    return guard(h,[&] { required(source); required(target); h->edges[source].push_back(target); });
}
int gc_set_entry(gc_handle* h,const char* name) {
    return guard(h,[&] { required(name); h->builder.entry(name); });
}
int gc_run(gc_handle* h,const char* initial,const char* checkpoint,int resume,const char* response,size_t max_steps) {
    return guard(h,[&] {
        for(const auto& e:h->edges) h->builder.edges(e.first,e.second);
        auto g=h->builder.compile(); Runtime runtime; RunOptions options; options.max_steps=max_steps;
        options.cancelled=&h->cancelled;
        options.on_event=[h](const std::string& type,const std::string& node) {
            if(h->observer) h->observer(type.c_str(),node.c_str(),h->observer_data);
        };
        std::unique_ptr<FileCheckpoint> store;
        if(checkpoint) store=std::make_unique<FileCheckpoint>(checkpoint);
        if(resume) {
            if(!store) throw Error("Resume requires checkpoint path");
            h->result=runtime.resume(g,*store,response?std::optional<std::string>(response):std::nullopt,options);
        } else { required(initial); h->result=runtime.invoke(g,decode_state(initial),store.get(),options); }
        h->wire=encode_state(h->result.state);
    });
}
int gc_inspect_checkpoint(gc_handle* h,const char* path) {
    return guard(h,[&] { required(path); FileCheckpoint store(path); h->result=store.load(); h->wire=encode_state(h->result.state); });
}
const char* gc_result(gc_handle* h) { return h?h->wire.c_str():""; }
const char* gc_prompt(gc_handle* h) { return h?h->result.prompt.c_str():""; }
int gc_suspended(gc_handle* h) { return h && h->result.suspended; }
size_t gc_steps(gc_handle* h) { return h?h->result.steps:0; }
int gc_reply_update(void* p,const char* key,const char* value) {
    return reply_guard(p,[&](Reply& r) { required(key); required(value); r.result.updates[key]=value; });
}
int gc_reply_next(void* p,const char* target) {
    return reply_guard(p,[&](Reply& r) { required(target); r.result.next=target; });
}
int gc_reply_suspend(void* p,const char* prompt) {
    return reply_guard(p,[&](Reply& r) { required(prompt); r.result.suspend=true; r.result.prompt=prompt; });
}
int gc_reply_error(void* p,const char* error) {
    return reply_guard(p,[&](Reply& r) { required(error); r.error=error; });
}
}
