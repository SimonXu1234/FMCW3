----------------------------------------------------------------------------------
-- top_module_lab.vhd
-- Lab (bench) top for DaVinci Pro A7 (XC7A35T-FGG484)
-- No RF front-end: internal test signal + internal muxout.
-- Data path: test signal -> adc(fir) -> control(bram) -> usb_sync -> FT232H
----------------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity top_module_lab is
    generic (
        -- Fixed frame length: each chirp uploads exactly this many 32-bit words
        -- (= sample pairs).  The ramp is made a little longer than
        -- MAX_ADC_SAMPLES / 2 MSPS so the counter always saturates and the frame
        -- length never varies -> the PC can reshape the stream into frames.
        MAX_ADC_SAMPLES : integer := 1000
    );
    port (
        sysclk      : in    std_logic;                       -- 50 MHz from board
        reset_n     : in    std_logic;                       -- active low
        led1        : out   std_logic;                       -- status LED

        -- USB (FT232H sync FIFO)
        usb_data    : inout std_logic_vector(7 downto 0);
        usb_rxf     : in    std_logic;
        usb_txe     : in    std_logic;
        usb_rd      : out   std_logic;
        usb_wr      : out   std_logic;
        usb_oe      : out   std_logic;
        usb_siwua   : out   std_logic;
        usb_clkout  : in    std_logic                        -- 60 MHz from FT232H
    );
end top_module_lab;

architecture Behavioral of top_module_lab is

    -- clocks
    signal clk_40mhz  : std_logic;
    signal clk_100mhz : std_logic;

    -- test signal
    signal test_cnt   : unsigned(11 downto 0) := (others => '0');
    signal adc_data_i : std_logic_vector(11 downto 0);

    -- adc outputs
    signal s_adc_a     : std_logic_vector(15 downto 0);
    signal s_adc_b     : std_logic_vector(15 downto 0);
    signal s_adc_valid : std_logic;

    -- muxout generator
    signal mux_cnt  : unsigned(23 downto 0) := (others => '0');
    signal muxout_i : std_logic := '0';

    -- control outputs
    signal s_adc_oe          : std_logic_vector(1 downto 0);
    signal s_adc_shdn        : std_logic_vector(1 downto 0);
    signal s_pa_en           : std_logic;
    signal s_mixer_en        : std_logic;
    signal s_usb_chipselect  : std_logic;
    signal s_usb_write_n     : std_logic;
    signal s_usb_writedata   : std_logic_vector(7 downto 0);
    signal s_ramp_done       : std_logic;
    signal s_tx_full         : std_logic;
    signal s_rx_empty        : std_logic;
    signal s_usb_readdata    : std_logic_vector(7 downto 0);

    -- microblaze wrapper signals (kept for later; data path does not use it)
    signal s_gpio            : std_logic_vector(15 downto 0);
    signal s_spi_cs          : std_logic_vector(0 to 0);
    signal s_spi_mosi        : std_logic;
    signal s_spi_sck         : std_logic;
    signal s_axi_txd_tdata   : std_logic_vector(31 downto 0);
    signal s_axi_txd_tlast   : std_logic;
    signal s_axi_txd_tvalid  : std_logic;
    signal s_axi_rxd_tdata   : std_logic_vector(31 downto 0);
    signal s_axi_rxd_tlast   : std_logic;
    signal s_axi_rxd_tready  : std_logic;
    signal s_axi_rxd_tvalid  : std_logic;

    -- LED blink
    signal led_cnt : unsigned(23 downto 0) := (others => '0');

    -- ILA probes
    signal s_probe0 : std_logic_vector(7 downto 0);
    signal s_probe1 : std_logic_vector(11 downto 0);
    signal s_probe2 : std_logic_vector(31 downto 0);
    signal s_probe3 : std_logic_vector(9 downto 0);

    -- tie-off constants
    constant CONFIG_DONE     : std_logic := '1';
    constant RAMP_CONFIGURED : std_logic := '1';
    constant SAMPLING_DONE   : std_logic := '0';

    -- components
    component clk_wiz_0
        port (
            clk_out1 : out std_logic;
            clk_out2 : out std_logic;
            resetn   : in  std_logic;
            clk_in1  : in  std_logic
        );
    end component;

    component adc
        port (
            clk      : in  std_logic;
            adc_data : in  std_logic_vector(11 downto 0);
            data_a   : out std_logic_vector(15 downto 0);
            data_b   : out std_logic_vector(15 downto 0);
            valid    : out std_logic
        );
    end component;

    component control
        generic (
            MAX_SAMPLES : integer
        );
        port (
            clk                        : in  std_logic;
            reset_n                    : in  std_logic;
            soft_reset_n               : in  std_logic;
            muxout                     : in  std_logic;
            adc_data_a                 : in  std_logic_vector(15 downto 0);
            adc_data_b                 : in  std_logic_vector(15 downto 0);
            adc_valid                  : in  std_logic;
            adc_oe                     : out std_logic_vector(1 downto 0);
            adc_shdn                   : out std_logic_vector(1 downto 0);
            pa_en                      : out std_logic;
            mixer_en                   : out std_logic;
            config_done                : in  std_logic;
            usb_chipselect             : out std_logic;
            usb_write_n                : out std_logic;
            usb_writedata              : out std_logic_vector(7 downto 0);
            usb_tx_full                : in  std_logic;
            microblaze_ramp_configured : in  std_logic;
            microblaze_sampling_done   : in  std_logic;
            ramp_done                  : out std_logic
        );
    end component;

    component usb_sync
        port (
            clk          : in    std_logic;
            reset_n      : in    std_logic;
            soft_reset_n : in    std_logic;
            read_n       : in    std_logic;
            write_n      : in    std_logic;
            chipselect   : in    std_logic;
            readdata     : out   std_logic_vector(7 downto 0);
            writedata    : in    std_logic_vector(7 downto 0);
            tx_full      : out   std_logic;
            rx_empty     : out   std_logic;
            usb_clock    : in    std_logic;
            usb_data     : inout std_logic_vector(7 downto 0);
            usb_rd_n     : out   std_logic;
            usb_wr_n     : out   std_logic;
            usb_oe_n     : out   std_logic;
            usb_rxf_n    : in    std_logic;
            usb_txe_n    : in    std_logic
        );
    end component;

    component microblaze_wrapper
        port (
            gpio_rtl_0_tri_o     : out std_logic_vector(15 downto 0);
            reset_rtl_0          : in  std_logic;
            spi0_mosi            : out std_logic;
            spi0_miso            : in  std_logic;
            spi0_sck             : out std_logic;
            spi0_cs              : out std_logic_vector(0 to 0);
            Clk                  : in  std_logic;
            AXI_STR_TXD_0_tdata  : out std_logic_vector(31 downto 0);
            AXI_STR_TXD_0_tlast  : out std_logic;
            AXI_STR_TXD_0_tready : in  std_logic;
            AXI_STR_TXD_0_tvalid : out std_logic;
            AXI_STR_RXD_0_tdata  : in  std_logic_vector(31 downto 0);
            AXI_STR_RXD_0_tlast  : in  std_logic;
            AXI_STR_RXD_0_tready : out std_logic;
            AXI_STR_RXD_0_tvalid : in  std_logic
        );
    end component;

    component ila_0
        port (
            clk    : in std_logic;
            probe0 : in std_logic_vector(7 downto 0);
            probe1 : in std_logic_vector(11 downto 0);
            probe2 : in std_logic_vector(31 downto 0);
            probe3 : in std_logic_vector(9 downto 0)
        );
    end component;

begin

    -- clock: 50 MHz in -> 40 MHz (logic) + 100 MHz (MicroBlaze)
    clk_wiz_0_inst : clk_wiz_0
    port map (
        clk_out1 => clk_40mhz,
        clk_out2 => clk_100mhz,
        resetn   => reset_n,
        clk_in1  => sysclk
    );

    -- test signal: 12-bit sawtooth (stand-in for ADC output)
    -- Held at 0 while muxout is low (the "gap"), so every stored frame starts
    -- with sample ~0.  That gives the PC a free frame-alignment check: word 0
    -- of every frame must be close to 0.
    process(clk_40mhz, reset_n)
    begin
        if reset_n = '0' then
            test_cnt <= (others => '0');
        elsif rising_edge(clk_40mhz) then
            if muxout_i = '0' then
                test_cnt <= (others => '0');
            else
                test_cnt <= test_cnt + 1;
            end if;
        end if;
    end process;

    adc_data_i <= std_logic_vector(test_cnt);

    -- muxout generator: 510 us high / 1000 us low @40 MHz
    --   510 us @ 2 MSPS = 1020 samples > MAX_ADC_SAMPLES (1000), so the store
    --   counter always saturates -> every frame carries exactly 1000 words.
    --   1000 us gap is enough to push 4000 bytes over the FT232H (~750 us at
    --   the measured 5.3 MB/s), so the FSM is back in IDLE before the next ramp.
    process(clk_40mhz, reset_n)
    begin
        if reset_n = '0' then
            mux_cnt  <= (others => '0');
            muxout_i <= '0';
        elsif rising_edge(clk_40mhz) then
            if mux_cnt = 60399 then
                mux_cnt <= (others => '0');
            else
                mux_cnt <= mux_cnt + 1;
            end if;
            if mux_cnt < 20400 then
                muxout_i <= '1';
            else
                muxout_i <= '0';
            end if;
        end if;
    end process;

    -- adc: dual-edge capture + FIR decimation
    adc_i : adc
    port map (
        clk      => clk_40mhz,
        adc_data => adc_data_i,
        data_a   => s_adc_a,
        data_b   => s_adc_b,
        valid    => s_adc_valid
    );

    -- control: RAMP (store) / GAP (upload)
    control_i : control
    generic map (
        MAX_SAMPLES => MAX_ADC_SAMPLES
    )
    port map (
        clk                        => clk_40mhz,
        reset_n                    => reset_n,
        soft_reset_n               => '1',
        muxout                     => muxout_i,
        adc_data_a                 => s_adc_a,
        adc_data_b                 => s_adc_b,
        adc_valid                  => s_adc_valid,
        adc_oe                     => s_adc_oe,
        adc_shdn                   => s_adc_shdn,
        pa_en                      => s_pa_en,
        mixer_en                   => s_mixer_en,
        config_done                => CONFIG_DONE,
        usb_chipselect             => s_usb_chipselect,
        usb_write_n                => s_usb_write_n,
        usb_writedata              => s_usb_writedata,
        usb_tx_full                => s_tx_full,   -- real backpressure: never overflow the FIFO
        microblaze_ramp_configured => RAMP_CONFIGURED,
        microblaze_sampling_done   => SAMPLING_DONE,
        ramp_done                  => s_ramp_done
    );

    -- usb sync fifo (FT232H)
    usb_sync_i : usb_sync
    port map (
        clk          => clk_40mhz,
        reset_n      => reset_n,
        soft_reset_n => '1',
        read_n       => '1',                          -- no config read in lab mode
        write_n      => s_usb_write_n,
        chipselect   => s_usb_chipselect,
        readdata     => s_usb_readdata,
        writedata    => s_usb_writedata,
        tx_full      => s_tx_full,
        rx_empty     => s_rx_empty,
        usb_clock    => usb_clkout,
        usb_data     => usb_data,
        usb_rd_n     => usb_rd,
        usb_wr_n     => usb_wr,
        usb_oe_n     => usb_oe,
        usb_rxf_n    => usb_rxf,
        usb_txe_n    => usb_txe
    );

    usb_siwua <= '1';                                 -- SIWU# inactive

    -- microblaze wrapper (kept for later; data path does not use it)
    mb_i : microblaze_wrapper
    port map (
        Clk                  => clk_100mhz,
        gpio_rtl_0_tri_o     => s_gpio,
        reset_rtl_0          => reset_n,
        spi0_cs              => s_spi_cs,
        spi0_miso            => '0',
        spi0_mosi            => s_spi_mosi,
        spi0_sck             => s_spi_sck,
        AXI_STR_RXD_0_tdata  => s_axi_rxd_tdata,
        AXI_STR_RXD_0_tlast  => s_axi_rxd_tlast,
        AXI_STR_RXD_0_tready => s_axi_rxd_tready,
        AXI_STR_RXD_0_tvalid => s_axi_rxd_tvalid,
        AXI_STR_TXD_0_tdata  => s_axi_txd_tdata,
        AXI_STR_TXD_0_tlast  => s_axi_txd_tlast,
        AXI_STR_TXD_0_tready => '0',                  -- no consumer in lab mode
        AXI_STR_TXD_0_tvalid => s_axi_txd_tvalid
    );

    -- AXI-Stream to MicroBlaze: idle (no config.vhd in lab mode)
    s_axi_rxd_tdata  <= (others => '0');
    s_axi_rxd_tlast  <= '0';
    s_axi_rxd_tvalid <= '0';

    -- LED: slow blink (~0.84 s period @40 MHz)
    process(clk_40mhz, reset_n)
    begin
        if reset_n = '0' then
            led_cnt <= (others => '0');
        elsif rising_edge(clk_40mhz) then
            led_cnt <= led_cnt + 1;
        end if;
    end process;

    led1 <= led_cnt(23);

    -- ILA probes
    s_probe0 <= s_usb_writedata;                             -- 8 bit: usb byte
    s_probe1 <= adc_data_i;                                  -- 12 bit: test signal
    s_probe2 <= s_adc_a & s_adc_b;                           -- 32 bit: FIR outputs
    s_probe3 <= "00" & s_adc_shdn & s_adc_oe
                & s_ramp_done & s_usb_write_n
                & s_usb_chipselect & muxout_i;               -- 10 bit: control flags

    ila_0_i : ila_0
    port map (
        clk    => clk_40mhz,
        probe0 => s_probe0,
        probe1 => s_probe1,
        probe2 => s_probe2,
        probe3 => s_probe3
    );

end Behavioral;