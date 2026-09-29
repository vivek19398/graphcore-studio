#pragma once
#include <atomic>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>
#include <utility>

namespace graphcore {
using State = std::map<std::string, std::string>;
inline constexpr const char* END = "__end__";
struct Error : std::runtime_error { using std::runtime_error::runtime_error; };
struct NodeResult {
    State updates;
    std::optional<std::string> next;
    bool suspend = false;
    std::string prompt;
    NodeResult(State changes = {}, std::optional<std::string> target = {},
               bool paused = false, std::string question = {})
        : updates(std::move(changes)), next(std::move(target)), suspend(paused),
          prompt(std::move(question)) {}
};
struct Context { bool resumed = false; std::string response; };
using Node = std::function<NodeResult(const State&, const Context&)>;
struct NodeOptions { unsigned retries = 0; }; // Only opt in for safe/idempotent nodes.
struct Snapshot {
    std::string graph_version, next;
    State state;
    std::size_t steps = 0;
    bool suspended = false;
    std::string prompt;
};
class CheckpointStore {
public:
    virtual ~CheckpointStore() = default;
    virtual void save(const Snapshot&) = 0;
    virtual Snapshot load() = 0;
};
class FileCheckpoint final : public CheckpointStore {
    std::filesystem::path path_;
public:
    explicit FileCheckpoint(std::filesystem::path path) : path_(std::move(path)) {}
    void save(const Snapshot&) override;
    Snapshot load() override;
};
class Graph {
public:
    struct Entry { Node fn; NodeOptions options; std::vector<std::string> targets; };
    std::map<std::string, Entry> nodes;
    std::string entry, version;
};
class GraphBuilder {
    Graph graph_;
public:
    explicit GraphBuilder(std::string version);
    GraphBuilder& add_node(std::string name, Node node, NodeOptions options = {});
    // All dynamic routes must be declared; the first is the default route.
    GraphBuilder& edges(const std::string& source, std::vector<std::string> targets);
    GraphBuilder& entry(std::string name);
    Graph compile() const;
};
struct RunOptions {
    std::size_t max_steps = 100;
    const std::atomic<bool>* cancelled = nullptr;
    // Observer exceptions are isolated from execution.
    std::function<void(const std::string&, const std::string&)> on_event;
};
class Runtime {
    Snapshot execute(const Graph&, Snapshot, CheckpointStore*, const RunOptions&, Context);
public:
    Snapshot invoke(const Graph&, State initial = {}, CheckpointStore* store = nullptr,
                    const RunOptions& options = {});
    // A response is required only when the saved snapshot is suspended.
    Snapshot resume(const Graph&, CheckpointStore&, std::optional<std::string> response = {},
                    const RunOptions& options = {});
};
// Portable text wire format shared by the C ABI and Python wrapper.
std::string encode_state(const State&);
State decode_state(const std::string&);
}
