#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <spirv/unified1/spirv.hpp>
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/environment.h"
#include "shader_recompiler/frontend/ir/ir_emitter.h"
#include "shader_recompiler/ir_opt/passes.h"
#include "shader_recompiler/object_pool.h"

using namespace Shader;
using Shader::Backend::SPIRV::EmitSPIRV;
static std::filesystem::path output_dir{"work/global16-modules"};

struct TestEnvironment final : Environment {
    TestEnvironment() { stage = Stage::Compute; }
    u64 ReadInstruction(u32) override { return 0; }
    u32 ReadCbufValue(u32, u32) override { return 0; }
    TextureType ReadTextureType(u32) override { return TextureType::Color2D; }
    TexturePixelFormat ReadTexturePixelFormat(u32) override { return TexturePixelFormat::R8_UNORM; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {1, 1, 1}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<ReplaceConstant> GetReplaceConstBuffer(u32, u32) override {
        return std::nullopt;
    }
    void Dump(u64, u64) override {}
};

[[noreturn]] static void fail(const char* what) {
    std::fprintf(stderr, "FAIL: %s\n", what);
    std::exit(1);
}

static std::vector<u32> emit_program(bool is_signed, u64 address, bool support_int64,
                                     bool lower_address) {
    ObjectPool<IR::Inst> inst_pool;
    IR::Block block{inst_pool};
    IR::Program program;
    program.stage = Stage::Compute;
    program.workgroup_size = {1, 1, 1};
    program.blocks.push_back(&block);
    program.post_order_blocks.push_back(&block);
    IR::AbstractSyntaxNode node{};
    node.type = IR::AbstractSyntaxNode::Type::Block;
    node.data.block = &block;
    program.syntax_list.push_back(node);
    IR::AbstractSyntaxNode ret{};
    ret.type = IR::AbstractSyntaxNode::Type::Return;
    program.syntax_list.push_back(ret);

    IR::IREmitter ir{block};
    IR::U64 guest_address;
    if (lower_address) {
        guest_address = ir.UConvert(64, ir.Imm32(static_cast<u32>(address)));
    } else {
        guest_address = ir.Imm64(address);
    }
    if (is_signed) {
        const IR::U32 value{ir.LoadGlobalS16(guest_address)};
        (void)ir.IAdd(value, ir.Imm32(1));
    } else {
        const IR::U32 value{ir.LoadGlobalU16(guest_address)};
        (void)ir.IAdd(value, ir.Imm32(1));
    }
    ir.Epilogue();

    TestEnvironment env;
    if (lower_address) Optimization::LowerInt64ToInt32(program);
    Optimization::CollectShaderInfoPass(env, program);
    if (!program.info.uses_global_memory) fail("CollectShaderInfoPass did not see the actual global load");

    Profile profile{};
    profile.supported_spirv = 0x00010600;
    profile.support_int64 = support_int64;
    return EmitSPIRV(profile, program);
}

struct Instruction {
    spv::Op op;
    std::vector<u32> words;
};

struct ModuleInfo {
    std::vector<Instruction> instructions;
    std::map<u32, u32> integer_widths;
    std::map<u32, u64> constants;
};

static ModuleInfo inspect(const std::vector<u32>& code) {
    if (code.size() < 5 || code[0] != spv::MagicNumber) fail("bad SPIR-V header");
    ModuleInfo result;
    for (size_t at = 5; at < code.size();) {
        const u32 count = code[at] >> 16;
        if (count == 0 || at + count > code.size()) fail("bad SPIR-V instruction length");
        const auto op = static_cast<spv::Op>(code[at] & 0xffffu);
        std::vector<u32> words(code.begin() + at + 1, code.begin() + at + count);
        if (op == spv::Op::OpTypeInt && words.size() >= 3) {
            result.integer_widths[words[0]] = words[1];
        } else if (op == spv::Op::OpConstant && words.size() >= 3) {
            const u32 type = words[0], id = words[1];
            const auto width_it = result.integer_widths.find(type);
            const u32 width = width_it == result.integer_widths.end() ? 0 : width_it->second;
            u64 value = words[2];
            if (width == 64 && words.size() >= 4) value |= static_cast<u64>(words[3]) << 32;
            result.constants[id] = value;
        } else if (op == spv::Op::OpConstantNull && words.size() >= 2) {
            result.constants[words[1]] = 0;
        }
        result.instructions.push_back({op, std::move(words)});
        at += count;
    }
    return result;
}

static u64 constant(const ModuleInfo& module, u32 id, const char* name) {
    const auto it = module.constants.find(id);
    if (it == module.constants.end()) fail(name);
    return it->second;
}

static std::vector<u32> save_module(const std::string& name, std::vector<u32> code) {
    std::filesystem::create_directories(output_dir);
    std::ofstream file(output_dir / (name + ".spv"), std::ios::binary);
    if (!file) fail("could not create emitted SPIR-V module");
    file.write(reinterpret_cast<const char*>(code.data()),
               static_cast<std::streamsize>(code.size() * sizeof(u32)));
    if (!file) fail("could not write emitted SPIR-V module");
    return code;
}

static void check_case(bool is_signed, u64 address, const char* name) {
    std::string filename;
    for (const char* c = name; *c; ++c) filename += (*c == ' ' ? '-' : *c);
    const auto module = inspect(save_module(filename, emit_program(is_signed, address, true, false)));
    const u64 expected_base = address & ~u64{3};
    const u32 expected_offset = static_cast<u32>((address & u64{3}) * 8u);
    if (expected_offset != 0 && expected_offset != 16)
        fail("test supplied an address not aligned to a halfword");

    u32 guest_id = 0, aligned_id = 0, lane64_id = 0, lane32_id = 0;
    u32 shift_id = 0, loaded_id = 0;
    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if (inst.op != spv::Op::OpConstant || w.size() < 3) continue;
        const auto type = module.integer_widths.find(w[0]);
        if (type != module.integer_widths.end() && type->second == 64 &&
            constant(module, w[1], "missing 64-bit constant") == address) {
            guest_id = w[1];
            break;
        }
    }
    if (!guest_id) fail("original 64-bit guest address is absent from the module");

    // Match main's LoadGlobalNarrow: both masks operate on the *full* U64 address.
    // The first preserves high address bits for the global U32 helper; the
    // second extracts only the two low lane bits before UConvert and << 3.
    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if (inst.op != spv::Op::OpBitwiseAnd || w.size() < 4 ||
            w[2] != guest_id) continue;
        const auto type = module.integer_widths.find(w[0]);
        if (type == module.integer_widths.end() || type->second != 64) continue;
        const u64 mask = constant(module, w[3], "non-constant guest address mask");
        if (mask == ~u64{3}) aligned_id = w[1];
        if (mask == u64{3}) lane64_id = w[1];
    }
    if (!aligned_id || !lane64_id)
        fail("missing full-width aligned base or low-lane address mask");
    if ((address & ~u64{3}) != expected_base)
        fail("aligned helper address lost the high bits");

    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if (inst.op == spv::Op::OpUConvert && w.size() >= 3 && w[2] == lane64_id) {
            const auto type = module.integer_widths.find(w[0]);
            if (type != module.integer_widths.end() && type->second == 32)
                lane32_id = w[1];
        }
        if (inst.op == spv::Op::OpFunctionCall && w.size() >= 4 && w[3] == aligned_id) {
            const auto type = module.integer_widths.find(w[0]);
            if (type != module.integer_widths.end() && type->second == 32)
                loaded_id = w[1];
        }
    }
    if (!lane32_id || !loaded_id)
        fail("missing lane U32 conversion or aligned U32 global helper call");

    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if (inst.op == spv::Op::OpShiftLeftLogical && w.size() >= 4 &&
            w[2] == lane32_id &&
            constant(module, w[3], "missing 3-bit byte offset shift") == 3u)
            shift_id = w[1];
    }
    if (!shift_id) fail("halfword bit offset is not derived from the masked lane");

    bool correct = false, wrong = false;
    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if ((inst.op == spv::Op::OpBitFieldSExtract ||
             inst.op == spv::Op::OpBitFieldUExtract) &&
            w.size() >= 5 && w[2] == loaded_id && w[3] == shift_id &&
            constant(module, w[4], "missing halfword width") == 16u) {
            const bool signed_op = inst.op == spv::Op::OpBitFieldSExtract;
            (signed_op == is_signed ? correct : wrong) = true;
        }
    }
    if (!correct || wrong)
        fail("wrong signedness or missing 16-bit extraction of the aligned U32 load");

    std::printf("PASS: %s -> U64-aligned helper, lane %u, %s halfword extraction (base=%016llx)\n",
                name, expected_offset, is_signed ? "signed" : "unsigned",
                static_cast<unsigned long long>(expected_base));
}

static void check_unsupported_profile() {
    const auto module = inspect(save_module(
        "unsupported-int64", emit_program(true, 0x0000000100000002ull, false, true)));
    u32 zero_id = 0;
    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if (inst.op == spv::Op::OpBitFieldSExtract || inst.op == spv::Op::OpBitFieldUExtract)
            fail("unsupported-int64 profile emitted a halfword extract instead of zero fallback");
        const auto type_width = w.empty() ? module.integer_widths.end()
                                          : module.integer_widths.find(w[0]);
        if (inst.op == spv::Op::OpConstant && w.size() >= 3 && w[2] == 0 &&
            type_width != module.integer_widths.end() && type_width->second == 32)
            zero_id = w[1];
    }
    bool zero_fallback_used = false;
    for (const auto& inst : module.instructions) {
        const auto& w = inst.words;
        if (inst.op == spv::Op::OpIAdd && w.size() >= 4 && w[2] == zero_id &&
            constant(module, w[3], "missing fallback's observable addend") == 1)
            zero_fallback_used = true;
    }
    if (!zero_id || !zero_fallback_used)
        fail("unsupported-int64 result was not the zero constant consumed by the fixture");
    std::puts("PASS: unsupported-int64 result is zero and emits no halfword extraction");
}

int main(int argc, char** argv) {
    if (argc == 2) output_dir = argv[1];
    check_case(true, 0x0000000100000000ull, "signed offset 0 high address");
    check_case(false, 0x0000000100000002ull, "unsigned offset 2 high address");
    check_case(true, 0x0000007f00000ffeull, "signed guest-page end 0xffe");
    check_case(false, 0x0000007f00000ffeull, "unsigned guest-page end 0xffe");
    check_unsupported_profile();
}
