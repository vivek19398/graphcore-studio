#include "graphcore/graphcore.hpp"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <sstream>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace graphcore {
namespace {
constexpr std::size_t MAX_FILE = 64 * 1024 * 1024;
std::string hex(const std::string& s) {
    static const char* digits = "0123456789abcdef";
    std::string out; out.reserve(s.size()*2);
    for (unsigned char c : s) { out += digits[c >> 4]; out += digits[c & 15]; }
    return out;
}
std::string unhex(const std::string& s) {
    if (s.size()%2) throw Error("Invalid hex length");
    auto digit = [](char c) -> unsigned {
        if(c >= '0' && c <= '9') return unsigned(c-'0');
        if(c >= 'a' && c <= 'f') return unsigned(c-'a'+10);
        throw Error("Invalid hex character");
    };
    std::string out; out.reserve(s.size()/2);
    for(std::size_t i=0;i<s.size();i+=2) out += char(digit(s[i])*16+digit(s[i+1]));
    return out;
}
void event(const RunOptions& o, const std::string& type, const std::string& node) {
    if(o.on_event) { try { o.on_event(type,node); } catch (...) {} }
}
void save(CheckpointStore* store, const Snapshot& s, const RunOptions& o) {
    if(store) { store->save(s); event(o,"checkpoint.committed",s.next); }
}
}
std::string encode_state(const State& state) {
    std::string out;
    for(const auto& item : state) out += hex(item.first)+":"+hex(item.second)+"\n";
    return out;
}
State decode_state(const std::string& wire) {
    if(wire.size()>MAX_FILE) throw Error("State exceeds 64 MiB wire limit");
    State out; std::istringstream in(wire); std::string line;
    while(std::getline(in,line)) {
        const auto colon=line.find(':');
        if(colon==std::string::npos) throw Error("Invalid state record");
        auto key=unhex(line.substr(0,colon));
        if(!out.emplace(key,unhex(line.substr(colon+1))).second) throw Error("Duplicate state key");
    }
    return out;
}
void FileCheckpoint::save(const Snapshot& s) {
    std::ostringstream data;
    data << "GRAPHCORE 1\n" << std::quoted(s.graph_version) << '\n'
         << std::quoted(s.next) << '\n' << s.steps << ' ' << s.suspended << '\n'
         << std::quoted(s.prompt) << '\n' << encode_state(s.state);
    auto bytes=data.str();
    if(bytes.size()>MAX_FILE) throw Error("Checkpoint exceeds 64 MiB limit");
    auto temp=path_; temp += ".tmp";
    {
        std::ofstream out(temp,std::ios::binary|std::ios::trunc);
        if(!out) throw Error("Cannot open checkpoint temporary file");
        out.write(bytes.data(),static_cast<std::streamsize>(bytes.size())); out.flush();
        if(!out) throw Error("Cannot write checkpoint");
        out.close(); if(!out) throw Error("Cannot close checkpoint");
    }
#ifdef _WIN32
    if(!MoveFileExW(temp.c_str(),path_.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
        throw Error("Cannot replace checkpoint: Windows error "+std::to_string(GetLastError()));
#else
    std::error_code ec;
    std::filesystem::rename(temp,path_,ec);
    if(ec) throw Error("Cannot replace checkpoint: "+ec.message());
#endif
}
Snapshot FileCheckpoint::load() {
    std::error_code ec; auto size=std::filesystem::file_size(path_,ec);
    if(ec || size>MAX_FILE) throw Error("Checkpoint missing or too large");
    std::ifstream in(path_,std::ios::binary);
    std::string magic; std::getline(in,magic);
    Snapshot s;
    if(magic!="GRAPHCORE 1" || !(in >> std::quoted(s.graph_version) >> std::quoted(s.next)
        >> s.steps >> s.suspended >> std::quoted(s.prompt))) throw Error("Invalid checkpoint header");
    if(in.get()!='\n') throw Error("Invalid checkpoint separator");
    std::ostringstream rest; rest << in.rdbuf(); s.state=decode_state(rest.str());
    return s;
}
GraphBuilder::GraphBuilder(std::string version) { graph_.version=std::move(version); }
GraphBuilder& GraphBuilder::add_node(std::string name, Node node, NodeOptions options) {
    if(name.empty() || name==END || !node) throw Error("Invalid node");
    if(!graph_.nodes.emplace(std::move(name),Graph::Entry{std::move(node),options,{}}).second)
        throw Error("Duplicate node");
    return *this;
}
GraphBuilder& GraphBuilder::edges(const std::string& source, std::vector<std::string> targets) {
    auto it=graph_.nodes.find(source); if(it==graph_.nodes.end()) throw Error("Unknown edge source");
    it->second.targets=std::move(targets); return *this;
}
GraphBuilder& GraphBuilder::entry(std::string name) { graph_.entry=std::move(name); return *this; }
Graph GraphBuilder::compile() const {
    if(graph_.version.empty()) throw Error("Graph version is required");
    if(!graph_.nodes.count(graph_.entry)) throw Error("Entry node is missing");
    for(const auto& pair : graph_.nodes) {
        if(pair.second.targets.empty()) throw Error("Node requires a declared target: "+pair.first);
        for(const auto& target : pair.second.targets)
            if(target!=END && !graph_.nodes.count(target)) throw Error("Unknown target: "+target);
    }
    return graph_;
}
Snapshot Runtime::invoke(const Graph& g, State initial, CheckpointStore* store, const RunOptions& o) {
    Snapshot s{g.version,g.entry,std::move(initial),0,false,{}};
    save(store,s,o); return execute(g,std::move(s),store,o,{});
}
Snapshot Runtime::resume(const Graph& g, CheckpointStore& store, std::optional<std::string> response,
                         const RunOptions& o) {
    auto s=store.load();
    if(s.graph_version!=g.version) throw Error("Graph version mismatch");
    if(s.next!=END && !g.nodes.count(s.next)) throw Error("Checkpoint node is missing");
    if(s.suspended != response.has_value()) throw Error("Supply a response exactly when checkpoint is suspended");
    Context ctx{s.suspended,response.value_or("")};
    s.suspended=false; s.prompt.clear();
    return execute(g,std::move(s),&store,o,ctx);
}
Snapshot Runtime::execute(const Graph& g, Snapshot s, CheckpointStore* store,
                          const RunOptions& o, Context ctx) {
    while(s.next!=END) {
        if(o.cancelled && o.cancelled->load()) throw Error("Run cancelled");
        if(s.steps>=o.max_steps) throw Error("Maximum total steps exceeded");
        auto it=g.nodes.find(s.next); if(it==g.nodes.end()) throw Error("Unknown scheduled node");
        const auto& node=it->second; NodeResult result;
        event(o,"node.started",s.next);
        for(unsigned attempt=0;;++attempt) {
            try { result=node.fn(s.state,ctx); break; }
            catch(...) {
                if(attempt>=node.options.retries) { event(o,"node.failed",s.next); throw; }
                if(o.cancelled && o.cancelled->load()) throw Error("Run cancelled");
                event(o,"node.retry",s.next);
            }
        }
        if(o.cancelled && o.cancelled->load()) throw Error("Run cancelled");
        Snapshot candidate=s;
        if(result.suspend) {
            if(!result.updates.empty() || result.next) throw Error("Suspended nodes cannot update state or route");
            candidate.suspended=true; candidate.prompt=std::move(result.prompt);
            save(store,candidate,o); event(o,"run.interrupted",s.next); return candidate;
        }
        auto target=result.next.value_or(node.targets.front());
        if(std::find(node.targets.begin(),node.targets.end(),target)==node.targets.end())
            throw Error("Node returned undeclared route: "+target);
        for(auto& update : result.updates) candidate.state[update.first]=std::move(update.second);
        candidate.next=target; ++candidate.steps;
        save(store,candidate,o); event(o,"node.completed",s.next);
        s=std::move(candidate); ctx={};
    }
    event(o,"run.completed",END); return s;
}
}
