#include "graphcore/graphcore.hpp"
#include <chrono>
#include <iostream>
#include <fstream>
using namespace graphcore;
namespace {
int checks=0;
void check(bool condition) { ++checks; if(!condition) throw Error("Check failed: "+std::to_string(checks)); }
template<class F> void fails(F fn) { bool caught=false; try { fn(); } catch(const std::exception&) { caught=true; } check(caught); }
Graph one(Node node,const std::string& version="v1",NodeOptions options={}) {
    return GraphBuilder(version).add_node("a",std::move(node),options).entry("a").edges("a",{END}).compile();
}
}
int main() {
    auto path=std::filesystem::temp_directory_path()/("graphcore-test-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    try {
        State special{{"", ""},{"new\nline",std::string("nul\0byte",8)},{"utf8","世界"}};
        check(decode_state(encode_state(special))==special);
        fails([] { decode_state("0:00\n"); });
        fails([] { decode_state("61:62\n61:63\n"); });
        fails([] { GraphBuilder("v1").compile(); });
        fails([] { GraphBuilder("v1").add_node("a",[](auto&,auto&) { return NodeResult{}; }).entry("a").edges("a",{"missing"}).compile(); });
        Runtime runtime; FileCheckpoint store(path);
        auto g=one([](const State&,const Context&) { return NodeResult{{{"value","42"}}}; });
        auto out=runtime.invoke(g,{},&store);
        check(out.state.at("value")=="42" && out.next==END && out.steps==1);
        check(store.load().state==out.state);
        check(runtime.resume(g,store).state==out.state);
        fails([&] { runtime.resume(one([](auto&,auto&) { return NodeResult{}; },"v2"),store); });
        auto approval=one([](const State&,const Context& ctx) {
            if(!ctx.resumed) return NodeResult{{},{},true,"Continue?"};
            return NodeResult{{{"answer",ctx.response}}};
        });
        check(runtime.invoke(approval,{},&store).suspended);
        fails([&] { runtime.resume(approval,store); });
        check(runtime.resume(approval,store,"yes").state.at("answer")=="yes");
        fails([&] { runtime.resume(approval,store,"yes"); });
        int calls=0;
        auto retry=one([&](auto&,auto&) { if(++calls==1) throw Error("transient"); return NodeResult{}; },"v1",{1});
        runtime.invoke(retry); check(calls==2);
        auto bad=one([](auto&,auto&) { return NodeResult{{{"bad","write"}},"unknown"}; });
        fails([&] { runtime.invoke(bad,{},&store); });
        check(store.load().steps==0 && store.load().state.empty());
        auto crash=one([](auto&,auto&) -> NodeResult { throw Error("simulated failure"); });
        fails([&] { runtime.invoke(crash,{{"kept","yes"}},&store); });
        check(runtime.resume(g,store).state.at("kept")=="yes");
        auto loop=GraphBuilder("v1").add_node("a",[](auto&,auto&) { return NodeResult{}; }).entry("a").edges("a",{"a"}).compile();
        RunOptions limited; limited.max_steps=3;
        fails([&] { runtime.invoke(loop,{},&store,limited); }); check(store.load().steps==3);
        std::atomic<bool> cancelled{true}; RunOptions cancellation; cancellation.cancelled=&cancelled;
        fails([&] { runtime.invoke(g,{},nullptr,cancellation); });
        RunOptions observer; observer.on_event=[](auto&,auto&) { throw Error("observer failure"); };
        check(runtime.invoke(g,{},nullptr,observer).next==END);
        { std::ofstream corrupt(path); corrupt << "not a checkpoint"; }
        fails([&] { store.load(); });
        std::filesystem::remove(path);
        std::cout << checks << " core checks passed\n"; return 0;
    } catch(const std::exception& e) {
        std::filesystem::remove(path); std::cerr << e.what() << '\n'; return 1;
    }
}
